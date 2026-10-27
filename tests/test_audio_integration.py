"""Tests for the production audio subsystem and its pipeline integration.

All tests are offline: fake engines, fake stores, fake HTTP clients and
``MockFoundryClient``. No Azure credentials or network access are required.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from api.pipeline_runner import _audio_emotion_event, _audio_perspective
from renderer.audio.bridge import (
    build_audio_request,
    card_text_for_language,
    canonical_language,
)
from renderer.audio.config import AudioSettings, _foundry_config_path
from renderer.audio.contract import (
    AudioRequest,
    AudioStore,
    SpeechEngine,
    SpeechError,
    StoredAudio,
    SynthesizedAudio,
)
from renderer.audio.script import SpokenScriptEnhancer
from renderer.audio.service import AudioService
from renderer.audio.ssml import build_ssml


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeEngine(SpeechEngine):
    name = "fake"
    audio_ext = "mp3"
    cache_version = "fake-v1"

    def __init__(self, *, fail_times: int = 0, delay_s: float = 0.0) -> None:
        self.calls = 0
        self.fail_times = fail_times
        self.delay_s = delay_s

    async def synthesize(self, req: AudioRequest) -> SynthesizedAudio:
        self.calls += 1
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise SpeechError("temporary speech failure", transient=True)
        return SynthesizedAudio(data=b"ID3" + req.text.encode(), duration_ms=1200)

    async def aclose(self) -> None:
        return None


class FakeStore(AudioStore):
    def __init__(self) -> None:
        self.objects: dict[str, StoredAudio] = {}
        self.puts = 0

    async def get(self, key: str, ext: str = "mp3") -> StoredAudio | None:
        return self.objects.get(key)

    async def put(
        self,
        key: str,
        data: bytes,
        duration_ms: int | None,
        ext: str = "mp3",
    ) -> StoredAudio:
        self.puts += 1
        stored = StoredAudio(
            url=f"https://audio.example/{key}.{ext}",
            duration_ms=duration_ms,
        )
        self.objects[key] = stored
        return stored

    async def aclose(self) -> None:
        return None


class FakeCredential:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def get_token(self, scope: str) -> Any:
        assert scope == "https://cognitiveservices.azure.com/.default"
        self.calls += 1
        return SimpleNamespace(token="test-token")

    def close(self) -> None:
        self.closed = True


class FakeHTTPResponse:
    status_code = 200
    content = b"MP3-BYTES"
    text = ""


class FakeHTTPClient:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> FakeHTTPResponse:
        self.posts.append({"url": url, **kwargs})
        return FakeHTTPResponse()

    async def get(self, url: str, **kwargs: Any) -> FakeHTTPResponse:
        return FakeHTTPResponse()


class FakeScriptClient:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def structured_output(
        self,
        agent_key: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any],
        *,
        timeout_s: float | None = None,
    ) -> Any:
        self.calls.append(
            {
                "agent_key": agent_key,
                "messages": messages,
                "schema": response_schema,
                "timeout_s": timeout_s,
            }
        )
        if self.error is not None:
            raise self.error
        return self.response


def make_request(text: str = "Goal for Nyota FC") -> AudioRequest:
    return AudioRequest(
        narration_id="card-test",
        text=text,
        language="en",
        emotion="excitement",
        intensity=0.75,
        voice_id="en-US-AriaNeural",
        match_minute=23,
        priority=1,
    )


# ---------------------------------------------------------------------------
# Configuration and placement regressions
# ---------------------------------------------------------------------------


def test_audio_package_is_nested_and_finds_repo_foundry_config() -> None:
    """The package must live in renderer/audio for parents[2] to be the repo."""
    config_path = _foundry_config_path()

    assert config_path == Path(__file__).resolve().parents[1] / "config" / "foundry_models.yaml"
    assert config_path.is_file()


def test_settings_accept_existing_env_aliases() -> None:
    settings = AudioSettings.from_env(
        {
            "SPEECH_ENDPOINT": "https://msim-dev-speech.cognitiveservices.azure.com/",
            "SPEECH_API_KEY": "local-key",
            "AUDIO_CONTAINER": "audio",
            "STORAGE_ACCOUNT_URL": "https://msimdevstor.blob.core.windows.net/",
            "ENVIRONMENT": "development",
        }
    )

    assert settings.speech_key == "local-key"
    assert settings.use_managed_identity is False
    assert settings.speech_endpoint.endswith(".cognitiveservices.azure.com/")
    assert settings.blob_account_url == "https://msimdevstor.blob.core.windows.net/"
    assert settings.blob_container == "audio"


def test_settings_default_to_managed_identity_when_no_key() -> None:
    settings = AudioSettings.from_env(
        {
            "SPEECH_ENDPOINT": "https://msim-dev-speech.cognitiveservices.azure.com/",
            "AUDIO_BLOB_ACCOUNT_URL": "https://msimdevstor.blob.core.windows.net/",
            "APP_ENV": "production",
        }
    )

    assert settings.speech_key is None
    assert settings.use_managed_identity is True


def test_settings_require_an_endpoint() -> None:
    with pytest.raises(RuntimeError, match="AZURE_SPEECH_REGION"):
        AudioSettings.from_env({"SPEECH_API_KEY": "key"})


# ---------------------------------------------------------------------------
# Azure Speech engine
# ---------------------------------------------------------------------------


def test_engine_uses_subscription_key_and_real_output_format() -> None:
    from renderer.audio.azure_engine import AzureTtsEngine

    async def run() -> tuple[SynthesizedAudio, FakeHTTPClient]:
        client = FakeHTTPClient()
        engine = AzureTtsEngine(key="secret", region="eastus", client=client)
        audio = await engine.synthesize(make_request())
        return audio, client

    audio, client = asyncio.run(run())

    assert audio.data == b"MP3-BYTES"
    assert audio.duration_ms and audio.duration_ms > 0
    request = client.posts[0]
    assert request["headers"]["Ocp-Apim-Subscription-Key"] == "secret"
    assert request["headers"]["X-Microsoft-OutputFormat"] == "audio-24khz-48kbitrate-mono-mp3"
    assert request["headers"]["Content-Type"] == "application/ssml+xml"
    assert request["content"].decode().startswith("<speak")
    assert "Goal for Nyota FC" in request["content"].decode()


def test_engine_uses_managed_identity_token() -> None:
    from renderer.audio.azure_engine import AzureTtsEngine

    credential = FakeCredential()

    async def run() -> None:
        engine = AzureTtsEngine(
            credential=credential,
            close_credential=True,
            region="eastus",
            client=FakeHTTPClient(),
        )
        await engine.synthesize(make_request())
        await engine.aclose()

    asyncio.run(run())

    assert credential.calls == 1
    assert credential.closed is True


def test_ssml_escapes_text_and_uses_swahili_locale() -> None:
    request = make_request("Nyota & Jua <wamefungwa>")
    request = AudioRequest(**{**request.__dict__, "language": "sw", "voice_id": "sw-KE-ZuriNeural"})

    ssml = build_ssml(request)

    assert 'xml:lang="sw-KE"' in ssml
    assert 'name="sw-KE-ZuriNeural"' in ssml
    assert "&amp;" in ssml
    assert "&lt;wamefungwa&gt;" in ssml


def test_ssml_adds_broadcast_breath_and_audible_excitement_prosody() -> None:
    request = make_request("Goli! Nyota wanasawazisha. Dakika ya 88.")
    request = AudioRequest(
        **{
            **request.__dict__,
            "language": "sw",
            "voice_id": "sw-KE-ZuriNeural",
            "intensity": 1.0,
        }
    )

    ssml = build_ssml(request)

    assert '<break time="110ms"/>' in ssml
    assert 'rate="+34%"' in ssml
    assert 'pitch="+18%"' in ssml
    assert 'volume="+32%"' in ssml


# ---------------------------------------------------------------------------
# Card bridge
# ---------------------------------------------------------------------------


def test_audio_emotion_reads_perspective_and_goal_text() -> None:
    assert _audio_perspective("home", "Nyota FC", "Nyota FC") == "favourable"
    assert _audio_perspective("home", "Jua United", "Nyota FC") == "unfavourable"
    assert _audio_perspective("neutral", "Jua United", "Nyota FC") == "neutral"

    goal_card = SimpleNamespace(text={"sw": {"headline": "Goli! Juma anafunga"}})
    card_card = SimpleNamespace(text={"sw": {"headline": "Kadi nyekundu"}})
    assert _audio_emotion_event(["big_chance"], goal_card) == "goal"
    assert _audio_emotion_event(["red_card"], card_card) == "red_card"
    assert _audio_emotion_event(["momentum_swing"], goal_card) == "goal"


def test_card_text_and_request_mapping_for_swahili() -> None:
    card = SimpleNamespace(
        card_id="card-1",
        card_type="goal",
        priority=1,
        match_seconds=88 * 60,
        text={"sw": {"headline": "Goli!", "body": "Nyota wanasawazisha."}},
    )

    assert canonical_language("sw-KE") == "sw"
    assert card_text_for_language(card, "sw") == "Goli! Nyota wanasawazisha."

    request = build_audio_request(
        card,
        language="sw",
        voice_id="sw-KE-ZuriNeural",
    )

    assert request is not None
    assert request.narration_id == "card-1"
    assert request.voice_id == "sw-KE-ZuriNeural"
    assert request.match_minute == 88
    assert request.emotion == "excitement"


def test_card_without_text_is_not_synthesized() -> None:
    card = {"card_id": "card-empty", "text": {}}

    assert build_audio_request(card, language="en", voice_id="en-US-AriaNeural") is None


def _spoken_card() -> SimpleNamespace:
    return SimpleNamespace(
        card_id="card-goal-1",
        card_type="goal",
        priority=1,
        match_seconds=31 * 60,
        text={
            "sw": {
                "headline": "Gool! Asha Njeri anafunga",
                "body": "Dakika ya 31, Asha Njeri anafunga kwa 0-2.",
            }
        },
        gloss_en={
            "headline": "Goal! Asha Njeri scores",
            "body": "In the 31st minute, Asha Njeri scores for 0-2.",
        },
    )


def test_spoken_script_enhancer_accepts_grounded_swahili_rewrite() -> None:
    client = FakeScriptClient(
        {
            "spoken_text": "Goli! Asha Njeri! Wanaongoza kwa 0-2 sasa.",
            "gloss_en": "Goal! Asha Njeri! They lead 0-2 now.",
        }
    )
    script = asyncio.run(
        SpokenScriptEnhancer(client).enhance(
            card=_spoken_card(),
            language="sw",
            event="goal",
            score_home=0,
            score_away=2,
            minute=31,
        )
    )

    assert script is not None
    assert script.text == "Goli! Asha Njeri! Wanaongoza kwa 0-2 sasa."
    assert script.gloss_en == "Goal! Asha Njeri! They lead 0-2 now."
    assert client.calls[0]["agent_key"] == "spoken_script_sw"


def test_spoken_script_enhancer_rejects_new_numbers_and_reversed_score() -> None:
    common = dict(
        card=_spoken_card(),
        language="sw",
        event="goal",
        score_home=0,
        score_away=2,
        minute=31,
    )
    new_number = FakeScriptClient(
        {
            "spoken_text": "Goli! Sasa ni 0-3 kwa Asha Njeri.",
            "gloss_en": "Goal! It is now 0-3 for Asha Njeri.",
        }
    )
    reversed_score = FakeScriptClient(
        {
            "spoken_text": "Goli! Asha Njeri! Wanaongoza kwa 2-0 sasa.",
            "gloss_en": "Goal! Asha Njeri! They lead 2-0 now.",
        }
    )

    assert asyncio.run(SpokenScriptEnhancer(new_number).enhance(**common)) is None
    assert asyncio.run(SpokenScriptEnhancer(reversed_score).enhance(**common)) is None


def test_spoken_script_enhancer_rejects_verbatim_caption_and_missing_gloss() -> None:
    verbatim = FakeScriptClient(
        {
            "spoken_text": (
                "Gool! Asha Njeri anafunga. "
                "Dakika ya 31, Asha Njeri anafunga kwa 0-2."
            ),
            "gloss_en": "Goal! Asha Njeri scores. In the 31st minute, 0-2.",
        }
    )
    no_gloss = FakeScriptClient(
        {
            "spoken_text": "Goli! Asha Njeri! Wanaongoza kwa 0-2 sasa.",
            "gloss_en": "",
        }
    )

    common = dict(
        card=_spoken_card(),
        language="sw",
        event="goal",
        score_home=0,
        score_away=2,
        minute=31,
    )
    assert asyncio.run(SpokenScriptEnhancer(verbatim).enhance(**common)) is None
    assert asyncio.run(SpokenScriptEnhancer(no_gloss).enhance(**common)) is None


def test_spoken_script_enhancer_falls_back_on_client_error() -> None:
    client = FakeScriptClient(error=RuntimeError("quota or timeout"))
    script = asyncio.run(
        SpokenScriptEnhancer(client).enhance(
            card=_spoken_card(),
            language="sw",
            event="goal",
            score_home=0,
            score_away=2,
            minute=31,
        )
    )

    assert script is None


def test_build_audio_request_keeps_approved_caption_as_source() -> None:
    request = build_audio_request(
        _spoken_card(),
        language="sw",
        voice_id="sw-KE-ZuriNeural",
        spoken_text="Goli! Asha Njeri! Wanaongoza kwa 0-2 sasa.",
        spoken_gloss_en="Goal! Asha Njeri! They lead 0-2 now.",
    )

    assert request is not None
    assert request.text == "Goli! Asha Njeri! Wanaongoza kwa 0-2 sasa."
    assert request.source_text == (
        "Gool! Asha Njeri anafunga Dakika ya 31, Asha Njeri anafunga kwa 0-2."
    )
    assert request.gloss_en == "Goal! Asha Njeri! They lead 0-2 now."


# ---------------------------------------------------------------------------
# Audio service behaviour
# ---------------------------------------------------------------------------


def test_service_synthesizes_once_then_uses_memo_cache() -> None:
    engine = FakeEngine()
    store = FakeStore()
    service = AudioService(engine, store)

    async def run() -> tuple[Any, Any]:
        return await service.render(make_request()), await service.render(make_request())

    first, second = asyncio.run(run())

    assert first.success and second.success
    assert first.audio_path == second.audio_path
    assert engine.calls == 1
    assert store.puts == 1


def test_service_coalesces_concurrent_requests() -> None:
    engine = FakeEngine(delay_s=0.02)
    service = AudioService(engine, FakeStore())

    async def run() -> list[Any]:
        return list(await asyncio.gather(*(service.render(make_request()) for _ in range(3))))

    results = asyncio.run(run())

    assert all(result.success for result in results)
    assert engine.calls == 1


def test_service_retries_transient_speech_errors() -> None:
    engine = FakeEngine(fail_times=1)
    service = AudioService(engine, FakeStore(), retries=1, retry_backoff_s=0)

    result = asyncio.run(service.render(make_request()))

    assert result.success is True
    assert engine.calls == 2


def test_service_opens_circuit_after_repeated_failures() -> None:
    engine = FakeEngine(fail_times=99)
    service = AudioService(
        engine,
        FakeStore(),
        retries=0,
        breaker_threshold=2,
        breaker_cooldown_s=60,
    )

    async def run() -> list[Any]:
        return [await service.render(make_request(f"line {i}")) for i in range(3)]

    results = asyncio.run(run())

    assert results[0].success is False
    assert results[1].success is False
    assert results[2].success is False
    assert results[2].error == "speech circuit is open"
    assert engine.calls == 2


def test_render_and_publish_emits_frontend_audio_update() -> None:
    service = AudioService(
        FakeEngine(),
        FakeStore(),
        voice_for=lambda language: "en-US-AriaNeural",
    )
    published: list[dict[str, Any]] = []

    async def publish(payload: dict[str, Any]) -> None:
        published.append(payload)

    result = asyncio.run(
        service.render_and_publish(
            make_request(),
            card_id="card-test",
            match_seconds=1380.0,
            publish=publish,
        )
    )

    assert result.success is True
    assert published == [
        {
            "type": "audio_update",
            "card_id": "card-test",
            "audio_url": result.audio_path,
            "duration_ms": result.duration_ms,
            "match_seconds": 1380.0,
        }
    ]


def test_render_and_publish_exposes_spoken_rewrite_for_audit() -> None:
    service = AudioService(
        FakeEngine(),
        FakeStore(),
        voice_for=lambda language: "sw-KE-ZuriNeural",
    )
    published: list[dict[str, Any]] = []
    base = make_request("Gool! Asha Njeri anafunga")
    request = AudioRequest(
        **{
            **base.__dict__,
            "language": "sw",
            "voice_id": "sw-KE-ZuriNeural",
            "text": "Goli! Asha Njeri! Wanaongoza kwa 0-2 sasa.",
            "source_text": "Gool! Asha Njeri anafunga",
            "gloss_en": "Goal! Asha Njeri! They lead 0-2 now.",
        }
    )

    async def publish(payload: dict[str, Any]) -> None:
        published.append(payload)

    result = asyncio.run(
        service.render_and_publish(
            request,
            card_id="card-spoken",
            match_seconds=1860.0,
            publish=publish,
        )
    )

    assert result.success is True
    assert published[0]["spoken_text"] == request.text
    assert published[0]["source_text"] == request.source_text
    assert published[0]["spoken_gloss_en"] == request.gloss_en


def test_render_and_publish_skips_existing_bundle_audio() -> None:
    engine = FakeEngine()
    service = AudioService(engine, FakeStore())
    published: list[dict[str, Any]] = []

    async def publish(payload: dict[str, Any]) -> None:
        published.append(payload)

    result = asyncio.run(
        service.render_and_publish(
            make_request(),
            card_id="card-bundle",
            match_seconds=60.0,
            publish=publish,
            existing_audio_url="https://audio.example/bundle.mp3",
            existing_duration_ms=900,
        )
    )

    assert result.audio_path == "https://audio.example/bundle.mp3"
    assert result.duration_ms == 900
    assert engine.calls == 0
    assert published[0]["audio_url"] == "https://audio.example/bundle.mp3"


# ---------------------------------------------------------------------------
# WebSocket delivery
# ---------------------------------------------------------------------------


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.texts: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: Any) -> None:
        self.texts.append(str(payload))

    async def send_text(self, payload: str) -> None:
        self.texts.append(payload)

    async def close(self) -> None:
        return None


def test_broadcast_message_targets_the_right_session() -> None:
    from api.websocket import WebSocketManager

    manager = WebSocketManager()
    ws_a = FakeWebSocket()
    ws_b = FakeWebSocket()

    async def run() -> None:
        await manager.connect(ws_a, session_id="a", match_id="m1")
        await manager.connect(ws_b, session_id="b", match_id="m1")
        await manager.broadcast_message(
            {"type": "audio_update", "card_id": "card-1", "audio_url": "u"},
            match_id="m1",
            session_id="a",
        )

    asyncio.run(run())

    assert any("audio_update" in text for text in ws_a.texts)
    assert not any("audio_update" in text for text in ws_b.texts)


# ---------------------------------------------------------------------------
# Pipeline wiring
# ---------------------------------------------------------------------------


class FakeAudioService:
    def __init__(self) -> None:
        self.rendered: list[str] = []
        self.requests: list[AudioRequest] = []

    def resolve_voice(self, language: str) -> str:
        return "en-US-AriaNeural"

    async def render_and_publish(
        self,
        request: AudioRequest,
        *,
        card_id: str,
        match_seconds: float,
        publish: Any,
        existing_audio_url: str | None = None,
    ) -> Any:
        self.rendered.append(card_id)
        self.requests.append(request)
        payload = {
            "type": "audio_update",
            "card_id": card_id,
            "audio_url": f"https://audio.example/{card_id}.mp3",
            "duration_ms": 1000,
            "match_seconds": match_seconds,
        }
        await publish(payload)
        return SimpleNamespace(
            success=True,
            audio_path=payload["audio_url"],
            duration_ms=1000,
        )


def test_pipeline_broadcasts_caption_then_audio_update() -> None:
    from api.pipeline_runner import run_pipeline_session
    from api.websocket import WebSocketManager
    from shared.foundry_client import MockFoundryClient

    mock_foundry = MockFoundryClient()
    for _ in range(50):
        mock_foundry.add_response(
            "explainer",
            {
                "theme": "control_vs_chaos",
                "reason": "The home team dominated possession.",
                "numeric_evidence": [],
                "evidence_event_ids": [],
                "partially_grounded": False,
            },
        )

    ws_manager = WebSocketManager()
    cards: list[dict[str, Any]] = []
    audio_updates: list[dict[str, Any]] = []
    order: list[str] = []

    async def mock_broadcast_card(match_id: str, card: Any, session_id: str) -> None:
        cards.append(card)
        order.append("card")

    async def mock_broadcast_clock(payload: Any, match_id: str) -> None:
        return None

    async def mock_broadcast_message(payload: Any, **kwargs: Any) -> None:
        audio_updates.append(payload)
        order.append("audio")

    ws_manager.broadcast_card = mock_broadcast_card  # type: ignore[method-assign]
    ws_manager.broadcast_clock = mock_broadcast_clock  # type: ignore[method-assign]
    ws_manager.broadcast_message = mock_broadcast_message  # type: ignore[method-assign]

    narration_cache: dict[str, Any] = {}
    bundle_entry = {
        "card_id": "card-bundle-test",
        "match_id": "comeback-from-two-down-42",
        "profile_key": "comeback-from-two-down-42.en.casual.neutral",
        "card_type": "key_moment",
        "text": {"en": {"headline": "Test bundle card", "body": "From bundle."}},
        "gloss_en": None,
        "from_bundle": True,
    }
    for km_seq in range(1, 30):
        moment_id = f"comeback-from-two-down-42-km-{km_seq:04d}"
        cache_key = f"comeback-from-two-down-42.en.casual.neutral:{moment_id}"
        narration_cache[cache_key] = dict(bundle_entry, moment_id=moment_id)

    audio_service = FakeAudioService()
    script_client = FakeScriptClient(
        {
            "spoken_text": "The moment: Test bundle card.",
            "gloss_en": "",
        }
    )

    async def run() -> None:
        await run_pipeline_session(
            "test-audio-session",
            "comeback-from-two-down-42",
            storyline="comeback_from_two_down",
            seed=42,
            speed=1000.0,
            language="en",
            mode="casual",
            ws_manager=ws_manager,
            foundry_client=mock_foundry,
            audio_script_client=script_client,
            audio_service=audio_service,
            narration_cache=narration_cache,
        )

    asyncio.run(run())

    assert cards, "the pipeline should emit at least one card"
    assert audio_service.rendered, "audio should be requested for emitted cards"
    assert audio_updates, "audio_update should reach the WebSocket gateway"
    assert script_client.calls, "the audio-script client should be used"
    assert any(
        request.source_text
        and request.source_text != request.text
        and request.text == "The moment: Test bundle card."
        for request in audio_service.requests
    ), "the approved caption should remain in source_text while audio uses the rewrite"

    card_ids = {card["card_id"] for card in cards}
    for update in audio_updates:
        assert update["type"] == "audio_update"
        assert update["card_id"] in card_ids
        assert update["audio_url"].startswith("https://audio.example/")

    # Audio is scheduled after the caption broadcast, never before it.
    first_audio = order.index("audio")
    assert "card" in order[:first_audio]
