"""
verify_azure_deployment.py

Post-deployment verification script. Run after `azd up` to confirm:
  1. Azure AI Speech has the required Swahili voices (sw-KE, sw-TZ).
  2. The Foundry model deployments exist and use model versions with
     retirement dates after 10 November 2026.

Usage:
    python scripts/verify_azure_deployment.py

Required environment variables (set by azd or manually):
    SPEECH_ENDPOINT        e.g. https://msim-dev-speech.cognitiveservices.azure.com/
    AZURE_CLIENT_ID        managed identity client ID (optional locally)
    FOUNDRY_ENDPOINT       e.g. https://msim-dev-foundry.openai.azure.com/
    FOUNDRY_API_KEY        optional; when absent, uses az login / managed identity
    SPEECH_API_KEY         optional; same fallback

Authentication defaults to DefaultAzureCredential, which uses the signed-in
Azure CLI account locally and the Container App managed identity in Azure.

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed (see stderr).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_VOICES = {
    "sw-KE": "sw-KE-ZuriNeural",
    "sw-TZ": "sw-TZ-RehemaNeural",
}

# Model versions and their retirement dates from the Foundry retirement
# schedule (checked 2026-10-26):
#   https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule
MODEL_RETIREMENT_FLOOR = datetime(2026, 11, 10, 23, 59, 0, tzinfo=timezone.utc)

KNOWN_RETIREMENTS: dict[str, datetime] = {
    "gpt-5.4:2026-03-05": datetime(2027, 9, 2, tzinfo=timezone.utc),
    "gpt-5.4-mini:2026-03-17": datetime(2027, 9, 21, tzinfo=timezone.utc),
}

REQUIRED_DEPLOYMENTS = {
    "msimulizi-explainer": "gpt-5.4-mini:2026-03-17",
    "msimulizi-narrator-sw": "gpt-5.4:2026-03-05",
    "msimulizi-narrator-en-fr": "gpt-5.4-mini:2026-03-17",
    "msimulizi-verifier": "gpt-5.4-mini:2026-03-17",
}


def _bearer_headers(scope: str) -> dict:
    """Acquire a token through DefaultAzureCredential (az login / MI)."""
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:  # pragma: no cover - declared dependency
        raise RuntimeError(
            "azure-identity is required for managed-identity checks. "
            "Run 'az login' or install azure-identity."
        ) from exc

    token = DefaultAzureCredential().get_token(scope).token
    return {"Authorization": f"Bearer {token}"}



def _get(url: str, headers: dict) -> dict:
    """Minimal HTTP GET using urllib (no external deps required)."""
    import urllib.request

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Check 1: Swahili voices
# ---------------------------------------------------------------------------

def check_speech_voices(speech_endpoint: str, api_key: str = "") -> list[str]:
    """Return a list of error messages (empty = all good)."""
    errors: list[str] = []
    # Resource endpoints expose the voice catalogue under /tts; the
    # region host (e.g. eastus2.tts.speech.microsoft.com) is not required.
    url = f"{speech_endpoint.rstrip('/')}/tts/cognitiveservices/voices/list"

    try:
        headers = (
            {"Ocp-Apim-Subscription-Key": api_key}
            if api_key
            else _bearer_headers("https://cognitiveservices.azure.com/.default")
        )
    except Exception as exc:
        return [f"Speech authentication failed: {exc}"]

    try:
        voices = _get(url, headers)
    except Exception as exc:
        return [f"Speech API unreachable: {exc}"]

    available: dict[str, list[str]] = {}
    for v in voices:
        locale = v.get("Locale", "")
        name = v.get("ShortName", "")
        available.setdefault(locale, []).append(name)

    for locale, expected_voice in REQUIRED_VOICES.items():
        locale_voices = available.get(locale, [])
        if expected_voice not in locale_voices:
            errors.append(
                f"Voice not found: {expected_voice} (locale {locale}). "
                f"Available in {locale}: {locale_voices or 'none'}"
            )
        else:
            print(f"  ✓ Voice available: {expected_voice}")

    return errors


# ---------------------------------------------------------------------------
# Check 2: Foundry model deployments and retirement dates
# ---------------------------------------------------------------------------

def _post(url: str, headers: dict, payload: dict) -> dict:
    """Minimal HTTP POST using urllib (no external deps required)."""
    import urllib.request

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def check_foundry_deployments(foundry_endpoint: str, api_key: str = "") -> list[str]:
    """Return a list of error messages (empty = all good).

    The Foundry data plane has no deployment-list endpoint. A tiny chat call
    to each deployment both proves the deployment exists and validates which
    model version is actually serving traffic.
    """
    errors: list[str] = []
    url = f"{foundry_endpoint.rstrip('/')}/openai/v1/chat/completions"

    try:
        headers = (
            {"api-key": api_key}
            if api_key
            else _bearer_headers("https://ai.azure.com/.default")
        )
    except Exception as exc:
        return [f"Foundry authentication failed: {exc}"]

    for deployment_name, model_key in REQUIRED_DEPLOYMENTS.items():
        payload = {
            "model": deployment_name,
            "messages": [
                {"role": "user", "content": "Reply with the single word OK."}
            ],
            "reasoning_effort": "none",
            "max_completion_tokens": 8,
        }

        try:
            data = _post(url, headers, payload)
        except Exception as exc:
            errors.append(f"Deployment {deployment_name}: chat call failed: {exc}")
            continue

        response_model = str(data.get("model", ""))
        expected_model = model_key.replace(":", "-")

        if not response_model.lower().startswith(expected_model.lower()):
            errors.append(
                f"Deployment {deployment_name}: expected model {model_key}, "
                f"but the response reports {response_model or 'no model'}"
            )
            continue

        retirement_date = KNOWN_RETIREMENTS.get(model_key)
        if retirement_date is None:
            errors.append(
                f"Deployment {deployment_name}: retirement date unknown for model {model_key}. "
                "Manually verify at https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule"
            )
        elif retirement_date < MODEL_RETIREMENT_FLOOR:
            errors.append(
                f"Deployment {deployment_name} ({model_key}): retirement date "
                f"{retirement_date.date()} is before 10 Nov 2026. Choose a newer model version."
            )
        else:
            print(
                f"  ✓ Deployment {deployment_name} ({model_key}): "
                f"retirement no earlier than {retirement_date.date()}"
            )

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    speech_endpoint = (
        os.environ.get("SPEECH_ENDPOINT")
        or os.environ.get("AZURE_SPEECH_ENDPOINT")
        or ""
    )
    speech_key = (
        os.environ.get("SPEECH_API_KEY")
        or os.environ.get("AZURE_SPEECH_KEY")
        or ""
    )
    foundry_endpoint = os.environ.get("FOUNDRY_ENDPOINT", "")
    foundry_key = os.environ.get("FOUNDRY_API_KEY", "")

    if not speech_endpoint or not foundry_endpoint:
        print(
            "ERROR: SPEECH_ENDPOINT and FOUNDRY_ENDPOINT must be set.\n"
            "Run 'azd up' first, then export the azd outputs; or set them manually.",
            file=sys.stderr,
        )
        return 1

    all_errors: list[str] = []

    print("\n── Checking Azure AI Speech Swahili voices ──")
    auth_mode = "API key" if speech_key else "managed identity / az login"
    print(f"  Authentication: {auth_mode}")
    all_errors.extend(check_speech_voices(speech_endpoint, speech_key))

    print("\n── Checking Foundry model deployments ──")
    auth_mode = "API key" if foundry_key else "managed identity / az login"
    print(f"  Authentication: {auth_mode}")
    all_errors.extend(check_foundry_deployments(foundry_endpoint, foundry_key))

    if all_errors:
        print("\n── FAILURES ──", file=sys.stderr)
        for e in all_errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    print("\n✓ All deployment checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
