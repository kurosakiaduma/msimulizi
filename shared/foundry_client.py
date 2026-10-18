"""
shared/foundry_client.py — Microsoft Foundry structured-output client.

Design points:
- ``FoundryClient`` wraps the Azure OpenAI SDK to call named deployments
  defined in ``config/foundry_models.yaml``.
- Every call enforces a 3-second asyncio timeout.
- Azure 429 responses raise a typed ``QuotaExceeded`` error.
- ``MockFoundryClient`` returns pre-scripted JSON for offline, deterministic tests.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
from typing import Any

import yaml  # pyyaml


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class QuotaExceeded(Exception):
    """Raised when Azure returns HTTP 429 or the budget guard is exhausted."""

    def __init__(self, message: str = "Model quota exceeded", *, agent: str = "") -> None:
        self.agent = agent
        super().__init__(message)


class FoundryTimeoutError(Exception):
    """Raised when a Foundry call does not return within the timeout."""


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config" / "foundry_models.yaml"


def _load_config() -> dict[str, Any]:
    with _CONFIG_PATH.open() as f:
        return yaml.safe_load(f)


def get_deployment(agent_key: str) -> dict[str, Any]:
    """Return the deployment config dict for *agent_key* (e.g. ``"explainer"``)."""
    cfg = _load_config()
    deployments = cfg.get("deployments", {})
    if agent_key not in deployments:
        raise KeyError(f"No deployment configured for agent key {agent_key!r}")
    return deployments[agent_key]


# ---------------------------------------------------------------------------
# FoundryClient
# ---------------------------------------------------------------------------

_CALL_TIMEOUT_SECONDS = 3.0


class FoundryClient:
    """
    Thin asyncio wrapper around the Azure OpenAI structured-output API.

    Parameters
    ----------
    endpoint:
        Azure OpenAI endpoint URL (e.g. ``https://<resource>.openai.azure.com``).
    api_key:
        Azure OpenAI API key.  Pass ``None`` to use managed identity (not
        supported in the fake / test path).
    """

    def __init__(self, endpoint: str, api_key: str | None = None) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._client: Any = None  # lazy-initialised on first call

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import AsyncAzureOpenAI  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "openai package is required for FoundryClient. "
                    "Install it with: pip install openai"
                ) from exc
            self._client = AsyncAzureOpenAI(
                azure_endpoint=self._endpoint,
                api_key=self._api_key,
                api_version="2024-08-01-preview",  # overridden per-call below
            )
        return self._client

    async def structured_output(
        self,
        agent_key: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call the deployment for *agent_key* with structured output.

        Parameters
        ----------
        agent_key:
            Key from ``config/foundry_models.yaml`` (e.g. ``"explainer"``).
        messages:
            OpenAI-style messages list.
        response_schema:
            JSON Schema for the expected response object.

        Returns
        -------
        dict
            Parsed JSON response object.

        Raises
        ------
        QuotaExceeded
            On HTTP 429.
        FoundryTimeoutError
            When the call exceeds ``_CALL_TIMEOUT_SECONDS``.
        """
        deployment = get_deployment(agent_key)
        deployment_name = deployment["deployment_name"]
        api_version = deployment.get("api_version", "2024-08-01-preview")

        client = self._get_client()
        # Override api_version per call via a fresh client with the pinned version.
        try:
            from openai import AsyncAzureOpenAI  # type: ignore[import]
            from openai import APIStatusError    # type: ignore[import]
        except ImportError as exc:
            raise ImportError("openai package required") from exc

        versioned_client = AsyncAzureOpenAI(
            azure_endpoint=self._endpoint,
            api_key=self._api_key,
            api_version=api_version,
        )

        async def _call() -> dict[str, Any]:
            try:
                response = await versioned_client.chat.completions.create(
                    model=deployment_name,
                    messages=messages,  # type: ignore[arg-type]
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "response",
                            "strict": True,
                            "schema": response_schema,
                        },
                    },
                )
            except APIStatusError as exc:
                if exc.status_code == 429:
                    raise QuotaExceeded(
                        f"Azure 429 on deployment {deployment_name!r}",
                        agent=agent_key,
                    ) from exc
                raise

            content = response.choices[0].message.content
            return json.loads(content)

        try:
            return await asyncio.wait_for(_call(), timeout=_CALL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise FoundryTimeoutError(
                f"Foundry call for {agent_key!r} timed out after {_CALL_TIMEOUT_SECONDS}s"
            ) from exc


# ---------------------------------------------------------------------------
# MockFoundryClient
# ---------------------------------------------------------------------------

class MockFoundryClient:
    """
    Deterministic mock for offline tests.

    Usage
    -----
    .. code-block:: python

        mock = MockFoundryClient()
        mock.add_response("explainer", {"theme": "control_vs_chaos", "reason": "Test."})
        result = await mock.structured_output("explainer", messages, schema)
        assert result["theme"] == "control_vs_chaos"

    If multiple responses are queued for the same *agent_key* they are returned
    in FIFO order.  If the queue is exhausted a ``RuntimeError`` is raised.

    Optionally, ``set_raise(agent_key, exc)`` makes the next call raise *exc*.
    """

    def __init__(self) -> None:
        self._responses: dict[str, list[dict[str, Any]]] = {}
        self._raises: dict[str, list[BaseException]] = {}
        self.calls: list[dict[str, Any]] = []  # call log for assertions

    def add_response(self, agent_key: str, response: dict[str, Any]) -> None:
        """Queue *response* to be returned by the next call for *agent_key*."""
        self._responses.setdefault(agent_key, []).append(response)

    def set_raise(self, agent_key: str, exc: BaseException) -> None:
        """Make the next call for *agent_key* raise *exc*."""
        self._raises.setdefault(agent_key, []).append(exc)

    async def structured_output(
        self,
        agent_key: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append({"agent_key": agent_key, "messages": messages})

        # Check for queued exceptions first.
        if self._raises.get(agent_key):
            exc = self._raises[agent_key].pop(0)
            raise exc

        if not self._responses.get(agent_key):
            raise RuntimeError(
                f"MockFoundryClient: no pre-scripted response for agent_key={agent_key!r}"
            )
        return self._responses[agent_key].pop(0)
