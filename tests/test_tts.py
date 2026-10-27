"""Tests for deterministic Azure Speech helpers and TTS retry/failure behavior."""

from __future__ import annotations

import asyncio

from renderer.tts import AzureSpeechSynthesizer, build_audio_key, synthesize_card_audio, voice_for_language


class FakePublisher:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def publish(self, payload: dict[str, object]):
        self.calls.append(payload)


class FakeBlob:
    def __init__(self):
        self.uploaded: dict[str, bytes] = {}

    def put(self, name: str, payload: bytes):
        self.uploaded[name] = payload


def test_voice_resolution_uses_verified_swahili_and_locale_variants():
    assert voice_for_language("sw-KE") == "sw-KE-ZuriNeural"
    assert voice_for_language("sw-TZ") == "sw-TZ-RehemaNeural"
    assert voice_for_language("fr-FR") == "fr-FR-DeniseNeural"
    assert voice_for_language("en-US") == "en-US-AriaNeural"


def test_audio_key_is_deterministic_and_uses_normalized_language():
    key_a = build_audio_key(language="sw-KE", voice="sw-KE-ZuriNeural", text="Hello world")
    key_b = build_audio_key(language="sw", voice="sw-KE-ZuriNeural", text="Hello world")
    assert key_a == key_b
    assert key_a.startswith("audio/sw/")
    assert key_a.endswith(".wav")


def test_synthesize_card_audio_reuses_existing_audio_url_without_tts():
    publisher = FakePublisher()
    blob = FakeBlob()
    calls = {"count": 0}

    class StubSynthesizer(AzureSpeechSynthesizer):
        async def synthesize(self, text: str, *, language: str, voice: str | None = None) -> bytes:
            calls["count"] += 1
            return b"audio-bytes"

    card = {
        "card_id": "card-123",
        "match_seconds": 123.0,
        "audio_url": "https://cdn.example/audio/reused.wav",
        "text": {"sw": {"headline": "Hodi", "body": "Mchezo umeanza"}},
    }

    result = asyncio.run(synthesize_card_audio(
        card,
        synthesizer=StubSynthesizer(blob_client=blob, publisher=publisher),
        language="sw",
    ))

    assert result == "https://cdn.example/audio/reused.wav"
    assert calls["count"] == 0
    assert publisher.calls == []
    assert blob.uploaded == {}


def test_synthesize_card_audio_failure_publishes_null():
    publisher = FakePublisher()

    class StubSynthesizer(AzureSpeechSynthesizer):
        async def synthesize(self, text: str, *, language: str, voice: str | None = None) -> bytes:
            raise RuntimeError("speech down")

    card = {
        "card_id": "card-fail",
        "match_seconds": 45.5,
        "text": {"en": {"headline": "Goal", "body": "The match changes"}},
    }

    result = asyncio.run(synthesize_card_audio(
        card,
        synthesizer=StubSynthesizer(publisher=publisher),
        language="en",
    ))

    assert result is None
    assert publisher.calls == [{"type": "audio_update", "card_id": "card-fail", "audio_url": None, "match_seconds": 45.5}]


def test_synthesize_card_audio_uploads_and_returns_url():
    publisher = FakePublisher()
    blob = FakeBlob()

    class StubSynthesizer(AzureSpeechSynthesizer):
        async def synthesize(self, text: str, *, language: str, voice: str | None = None) -> bytes:
            return b"wav-data"

    card = {
        "card_id": "card-upload",
        "match_seconds": 90.0,
        "text": {"fr": {"headline": "But", "body": "Le score change"}},
    }

    result = asyncio.run(synthesize_card_audio(
        card,
        synthesizer=StubSynthesizer(blob_client=blob, publisher=publisher, storage_url="https://cdn.example"),
        language="fr",
    ))

    assert result is not None
    assert result.startswith("https://cdn.example")
    assert "audio/fr/" in result
    assert blob.uploaded
    assert publisher.calls[0]["audio_url"] == result
