"""Microsoft Agent Framework orchestrator for the Msimulizi match pipeline.

The project uses a small deterministic workflow around the existing agent
components. The orchestrator is intentionally lightweight: it exposes a single
`run()` API, tracks per-session state, and can optionally wrap a
`WorkflowBuilder` from the Microsoft Agent Framework when the dependency is
available.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from agent_framework import Executor, WorkflowBuilder, WorkflowContext, handler


@dataclass
class SessionRunState:
    """In-memory state kept for each orchestrated replay session."""

    session_id: str
    match_id: str | None = None
    speed: float = 1.0
    state: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: asyncio.get_running_loop().time())


class _NullWorkflow:
    """Fallback workflow used when the Agent Framework package is absent."""

    def __init__(self, orchestrator: "Orchestrator") -> None:
        self.orchestrator = orchestrator

    def run(self, payload: Any) -> Any:
        return {"status": "ok", "payload": payload, "source": "null_workflow"}

    async def arun(self, payload: Any) -> Any:
        return self.run(payload)


class Orchestrator:
    """Single-process orchestration entry point for the Msimulizi pipeline."""

    def __init__(
        self,
        *,
        session_store: dict[str, SessionRunState] | None = None,
        workflow_factory: Callable[[], Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.session_store = session_store if session_store is not None else {}
        self.workflow_factory = workflow_factory or self._build_default_workflow
        self.workflow = self.workflow_factory()
        self.kwargs = kwargs
        self.agents: dict[str, Any] = {}

    def register_agent(self, name: str, agent: Any) -> Any:
        """Register a named agent or callable step in the orchestrator graph."""
        self.agents[name] = agent
        return agent

    add_agent = register_agent

    def handle_quota_exceeded(self, *, agent: str | None = None, detail: Any | None = None) -> dict[str, Any]:
        """Return a consistent quota-exceeded payload for fallback paths."""
        return {"status": "quota_exceeded", "agent": agent, "detail": detail, "fallback": "bundle_or_fallback"}

    def route(self, payload: Any, *, session_id: str | None = None) -> Any:
        """Dispatch payloads to a named agent when a matching registration exists."""
        if isinstance(payload, dict):
            agent_name = str(payload.get("agent") or payload.get("agent_key") or "")
            if agent_name and agent_name in self.agents:
                target = self.agents[agent_name]
                if callable(target):
                    return target(payload)
        return payload

    def _build_default_workflow(self) -> Any:
        if WorkflowBuilder is None:
            return _NullWorkflow(self)

        class StartExecutor(Executor):
            @handler
            async def process(self, payload: dict[str, Any], ctx: WorkflowContext[None, dict[str, Any]]) -> None:  # type: ignore[misc]
                await ctx.yield_output({
                    "status": "accepted",
                    "payload": payload,
                    "source": "agent_framework",
                })

        executor = StartExecutor(id="orchestrator_start")
        return WorkflowBuilder(start_executor=executor, output_from=[executor]).build()

    def create_session(self, *, session_id: str | None = None, match_id: str | None = None, speed: float = 1.0) -> SessionRunState:
        """Create or return a per-session orchestration state bucket."""
        resolved_session = session_id or f"session-{len(self.session_store) + 1}"
        record = self.session_store.get(resolved_session)
        if record is None:
            record = SessionRunState(session_id=resolved_session, match_id=match_id, speed=speed)
            self.session_store[resolved_session] = record
        else:
            if match_id is not None:
                record.match_id = match_id
            record.speed = speed
        return record

    def session_for(self, session_id: str | None = None) -> SessionRunState | None:
        if session_id is None:
            if not self.session_store:
                return None
            return next(iter(self.session_store.values()))
        return self.session_store.get(session_id)

    async def arun(self, payload: Any, *, session_id: str | None = None, match_id: str | None = None, speed: float = 1.0) -> Any:
        session = self.create_session(session_id=session_id, match_id=match_id, speed=speed)
        if hasattr(self.workflow, "run"):
            if inspect.iscoroutinefunction(getattr(self.workflow, "run", None)):
                result = await self.workflow.run(payload)
            else:
                result = self.workflow.run(payload)
                if inspect.isawaitable(result):
                    result = await result
            if hasattr(result, "get_outputs"):
                outputs = result.get_outputs()
                if outputs:
                    return outputs
                return result.get_intermediate_outputs() if hasattr(result, "get_intermediate_outputs") else []
            return result
        return {"status": "ok", "payload": payload, "session_id": session.session_id, "source": "orchestrator"}

    def run(self, payload: Any, *, session_id: str | None = None, match_id: str | None = None, speed: float = 1.0) -> Any:
        """Synchronously execute a single orchestration request."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.arun(payload, session_id=session_id, match_id=match_id, speed=speed))
        # Running inside an existing event loop is uncommon for the sync entry
        # point; prefer a direct coroutine execution path rather than blocking the
        # current thread.
        return self.arun(payload, session_id=session_id, match_id=match_id, speed=speed)

    def build(self) -> Any:
        """Compatibility alias for workflow builders or tests expecting a build step."""
        return self.workflow

    def build_workflow(self) -> Any:
        return self.workflow

    def create_workflow(self) -> Any:
        return self.workflow

    def __call__(self, payload: Any, *, session_id: str | None = None, match_id: str | None = None, speed: float = 1.0) -> Any:
        return self.run(payload, session_id=session_id, match_id=match_id, speed=speed)

    async def run_session(self, *, session_id: str | None = None, payload: Any | None = None) -> Any:
        """Convenience method used by session-oriented callers."""
        return await self.arun(payload or {}, session_id=session_id)

    async def process(self, payload: Any, *, session_id: str | None = None, match_id: str | None = None, speed: float = 1.0) -> Any:
        """Compatibility alias for orchestration code that calls `.process()`."""
        return await self.arun(payload, session_id=session_id, match_id=match_id, speed=speed)


__all__ = [
    "Orchestrator",
    "SessionRunState",
]
