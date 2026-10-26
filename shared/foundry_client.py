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
import os
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
        Azure OpenAI API key. Pass ``None`` to authenticate with managed
        identity through ``DefaultAzureCredential``.
    """

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        *,
        use_managed_identity: bool | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._api_key = api_key
        self._use_managed_identity = (
            use_managed_identity if use_managed_identity is not None else not api_key
        )

        if not api_key and not self._use_managed_identity:
            raise ValueError(
                "FoundryClient needs an API key or managed-identity authentication"
            )

        self._credential: Any = None
        self._client: Any = None

    def _build_client(self) -> Any:
        """Create the shared v1-API client on first use.

        The v1 endpoint removes dated ``api-version`` pinning, which is
        important because newer Foundry models are not served by the old
        preview API versions. The deployment name remains the model argument.
        """
        if self._client is not None:
            return self._client

        try:
            from openai import AsyncOpenAI  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "openai package is required for FoundryClient. "
                "Install it with: pip install openai"
            ) from exc

        base_url = self._endpoint.rstrip("/")
        if not base_url.endswith("/openai/v1"):
            base_url += "/openai/v1/"
        else:
            base_url += "/"
        kwargs: dict[str, Any] = {"base_url": base_url, "max_retries": 0}

        if self._use_managed_identity and not self._api_key:
            # Container Apps injects AZURE_CLIENT_ID for the user-assigned
            # identity; DefaultAzureCredential consumes it automatically.
            from azure.identity.aio import (  # type: ignore[import]
                DefaultAzureCredential,
                get_bearer_token_provider,
            )

            if self._credential is None:
                self._credential = DefaultAzureCredential()

            kwargs["api_key"] = get_bearer_token_provider(
                self._credential,
                "https://ai.azure.com/.default",
            )
        else:
            kwargs["api_key"] = self._api_key

        self._client = AsyncOpenAI(**kwargs)
        return self._client

    def _get_client(self, api_version: str | None = None) -> Any:
        # ``api_version`` is accepted for callers written before the v1 API
        # migration; it is ignored because v1 is unversioned.
        return self._build_client()

    async def aclose(self) -> None:
        """Close the SDK client and the managed-identity credential."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # pragma: no cover - shutdown best effort
                pass
            self._client = None

        if self._credential is not None:
            try:
                await self._credential.close()
            except Exception:  # pragma: no cover - shutdown best effort
                pass
            self._credential = None

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

        client = self._get_client()

        try:
            from openai import APIStatusError  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ImportError("openai package required") from exc

        request_options: dict[str, Any] = {}
        reasoning_effort = os.getenv("FOUNDRY_REASONING_EFFORT", "none").strip()
        if reasoning_effort:
            # The 3-second contract leaves no room for hidden reasoning. The
            # default keeps calls inside that budget; raise it deliberately
            # if a deployment needs deeper reasoning and the budget allows.
            request_options["reasoning_effort"] = reasoning_effort

        max_completion_tokens = os.getenv("FOUNDRY_MAX_COMPLETION_TOKENS", "").strip()
        if max_completion_tokens:
            try:
                request_options["max_completion_tokens"] = int(max_completion_tokens)
            except ValueError:
                pass

        async def _call() -> dict[str, Any]:
            try:
                response = await client.chat.completions.create(
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
                    **request_options,
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
