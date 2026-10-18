"""
shared/content_safety.py — Azure AI Content Safety wrapper.

Design points:
- ``ContentSafetyClient`` wraps the Azure AI Content Safety REST API.
- All checks return either ``Allowed`` or ``Blocked`` — callers decide what
  to do (KM cards substitute a Fallback Line, stat/spotlight cards are dropped,
  correction edits are rejected).
- Every ``Blocked`` result is logged with the category, severity, and context
  label supplied by the caller.
- ``MockContentSafetyClient`` is a deterministic stand-in for offline tests;
  callers pre-configure which texts are blocked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Allowed:
    """Text passed all content safety checks."""
    text: str


@dataclass(frozen=True)
class Blocked:
    """
    Text was blocked by Azure AI Content Safety.

    Attributes
    ----------
    text:
        The original input text.
    category:
        The Content Safety category that triggered the block
        (e.g. ``"Hate"``, ``"Violence"``, ``"Sexual"``, ``"SelfHarm"``).
    severity:
        Integer severity level returned by the API (0–6 scale; the block
        threshold is configurable on the Azure resource).
    context:
        Caller-supplied label for logging (e.g. ``"key_moment"``,
        ``"stat_card"``, ``"correction_edit"``).
    """
    text: str
    category: str
    severity: int
    context: str


# Union alias used in type annotations throughout the codebase.
SafetyResult = Allowed | Blocked


# ---------------------------------------------------------------------------
# Protocol (structural typing)
# ---------------------------------------------------------------------------

@runtime_checkable
class ContentSafetyClientProtocol(Protocol):
    async def check(self, text: str, *, context: str = "") -> SafetyResult: ...


# ---------------------------------------------------------------------------
# Live client
# ---------------------------------------------------------------------------

class ContentSafetyClient:
    """
    Wraps the Azure AI Content Safety ``analyzeText`` API.

    Parameters
    ----------
    endpoint:
        Azure AI Content Safety endpoint URL
        (e.g. ``https://<resource>.cognitiveservices.azure.com``).
    api_key:
        Subscription key.  Pass ``None`` to use managed identity via the
        ``azure-identity`` package (not supported in the mock path).
    block_threshold:
        Minimum severity that triggers a ``Blocked`` result.  Defaults to 2
        (medium), matching Azure's ``AcceptableMediumSeverityContentThreshold``
        preset.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        *,
        block_threshold: int = 2,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._api_key = api_key
        self._block_threshold = block_threshold
        self._http_client: Any = None  # lazy-initialised

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Ocp-Apim-Subscription-Key"] = self._api_key
        return headers

    async def check(self, text: str, *, context: str = "") -> SafetyResult:
        """
        Analyse *text* with Azure AI Content Safety.

        Returns ``Allowed`` if every category's severity is below the block
        threshold; returns ``Blocked`` (and logs the event) for the first
        category that meets or exceeds it.

        Raises
        ------
        RuntimeError
            If the HTTP request fails (caller should treat this as a transient
            error and retry or fall back).
        """
        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "httpx is required for ContentSafetyClient. "
                "Install it with: pip install httpx"
            ) from exc

        url = f"{self._endpoint}/contentsafety/text:analyze?api-version=2023-10-01"
        payload = {
            "text": text,
            "categories": ["Hate", "Violence", "Sexual", "SelfHarm"],
        }

        if self._http_client is None:
            self._http_client = httpx.AsyncClient()

        response = await self._http_client.post(
            url, json=payload, headers=self._get_headers()
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Content Safety API returned {response.status_code}: {response.text}"
            )

        data = response.json()
        categories_analysis = data.get("categoriesAnalysis", [])

        for entry in categories_analysis:
            category = entry.get("category", "Unknown")
            severity = entry.get("severity", 0)
            if severity >= self._block_threshold:
                result = Blocked(
                    text=text,
                    category=category,
                    severity=severity,
                    context=context,
                )
                logger.warning(
                    "Content Safety blocked text | context=%r category=%r severity=%d",
                    context,
                    category,
                    severity,
                )
                return result

        return Allowed(text=text)


# ---------------------------------------------------------------------------
# Mock client
# ---------------------------------------------------------------------------

class MockContentSafetyClient:
    """
    Deterministic mock for offline tests.

    Usage
    -----
    .. code-block:: python

        mock = MockContentSafetyClient()
        mock.add_blocked("bad text", category="Hate", severity=4)
        result = await mock.check("bad text", context="key_moment")
        assert isinstance(result, Blocked)

    Texts not listed in the blocked set are returned as ``Allowed``.
    The ``calls`` list records every ``check`` invocation for assertions.
    """

    def __init__(self) -> None:
        self._blocked: dict[str, tuple[str, int]] = {}  # text -> (category, severity)
        self.calls: list[dict[str, Any]] = []

    def add_blocked(
        self, text: str, *, category: str = "Hate", severity: int = 4
    ) -> None:
        """Register *text* as blocked with the given *category* and *severity*."""
        self._blocked[text] = (category, severity)

    async def check(self, text: str, *, context: str = "") -> SafetyResult:
        self.calls.append({"text": text, "context": context})

        if text in self._blocked:
            category, severity = self._blocked[text]
            result = Blocked(
                text=text,
                category=category,
                severity=severity,
                context=context,
            )
            logger.warning(
                "MockContentSafety blocked text | context=%r category=%r severity=%d",
                context,
                category,
                severity,
            )
            return result

        return Allowed(text=text)
