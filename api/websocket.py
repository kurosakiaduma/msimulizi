"""WebSocket gateway: manage connections and push real-time messages to viewers.

This module exposes a WebSocketManager that stores active connections per
session and provides helpers the renderer/orchestrator can call to push cards
and clock updates to connected viewers.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        # session_id -> connection metadata; metadata keeps profile/session routing
        self._connections: Dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        # background pinger
        self._pinger_task: asyncio.Task | None = None

    def _connection_ws(self, connection: dict[str, Any] | WebSocket) -> WebSocket | None:
        if isinstance(connection, dict):
            return connection.get("ws")
        return connection

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str | None = None,
        *,
        profile_key: str | None = None,
        match_id: str | None = None,
    ) -> str:
        await websocket.accept()
        sid = session_id or f"session-{int(time.time() * 1000)}"
        async with self._lock:
            self._connections[sid] = {
                "session_id": sid,
                "ws": websocket,
                "profile_key": profile_key,
                "match_id": match_id,
            }
        # start pinger when first connection arrives
        if self._pinger_task is None or self._pinger_task.done():
            self._pinger_task = asyncio.create_task(self._pinger())
        await websocket.send_json({"type": "welcome", "session_id": sid})
        return sid

    async def disconnect(self, session_id: str) -> None:
        async with self._lock:
            entry = self._connections.pop(session_id, None)
            ws = self._connection_ws(entry)
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass

    async def send(self, session_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            entry = self._connections.get(session_id)
        ws = self._connection_ws(entry)
        if ws is None:
            return
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            # drop dead connections
            await self.disconnect(session_id)

    def _matches_target(
        self,
        entry: dict[str, Any],
        *,
        session_id: str | None = None,
        profile_key: str | None = None,
        match_id: str | None = None,
    ) -> bool:
        if session_id is not None and entry.get("session_id") != session_id:
            return False
        if profile_key is not None:
            connection_profile = entry.get("profile_key")
            if connection_profile and connection_profile != profile_key:
                return False
            if connection_profile is None and profile_key is not None:
                return False
        if match_id is not None:
            connection_match = entry.get("match_id")
            if connection_match and connection_match != match_id:
                return False
            if connection_match is None and match_id is not None:
                return False
        return True

    async def broadcast_card(
        self,
        match_id: str,
        card: dict[str, Any],
        *,
        profile_key: str | None = None,
        session_id: str | None = None,
    ) -> None:
        payload = {"type": "card", "match_id": match_id, "card": card}
        async with self._lock:
            conns = list(self._connections.items())
        for sid, entry in conns:
            if not self._matches_target(entry, session_id=session_id, profile_key=profile_key, match_id=match_id):
                continue
            ws = entry.get("ws")
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                await self.disconnect(sid)

    async def broadcast_clock(self, clock_payload: dict[str, Any], *, match_id: str | None = None, profile_key: str | None = None) -> None:
        payload = {"type": "clock_update", "clock": clock_payload}
        async with self._lock:
            conns = list(self._connections.items())
        for sid, entry in conns:
            if not self._matches_target(entry, profile_key=profile_key, match_id=match_id):
                continue
            ws = entry.get("ws")
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                await self.disconnect(sid)

    async def _pinger(self) -> None:
        try:
            while True:
                await asyncio.sleep(30.0)
                async with self._lock:
                    conns = list(self._connections.items())
                ping = {"type": "ping", "ts": time.time()}
                for sid, entry in conns:
                    ws = entry.get("ws")
                    try:
                        await ws.send_text(json.dumps(ping))
                    except Exception:
                        await self.disconnect(sid)
        except asyncio.CancelledError:
            return


# Helper websocket endpoint function for FastAPI wiring
async def websocket_endpoint(websocket: WebSocket, manager: WebSocketManager, session_manager: Any) -> None:
    # Accept and register the connection. If client supplied session_id it will be in query params
    session_id = websocket.query_params.get("session_id")
    profile_key = websocket.query_params.get("profile_key")
    match_id = websocket.query_params.get("match_id")
    sid = await manager.connect(websocket, session_id=session_id, profile_key=profile_key, match_id=match_id)
    # touch the session record if present
    if session_manager is not None and getattr(session_manager, "touch", None):
        session_manager.touch(sid)
    try:
        while True:
            text = await websocket.receive_text()
            # Expect JSON commands: {"type":"profile_update","payload":{...}} etc.
            try:
                data = json.loads(text)
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "message": "invalid_json"}))
                continue
            cmd = data.get("type")
            if cmd == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "ts": time.time()}))
                continue
            if cmd == "profile_update":
                # update session metadata when present
                meta = data.get("payload") or {}
                if session_manager is not None and getattr(session_manager, "get", None):
                    rec = session_manager.get(sid)
                    if rec is not None:
                        rec.metadata.update(meta)
                        session_manager.touch(sid)
                profile_key = meta.get("profile_key") or profile_key
                match_id = meta.get("match_id") or match_id
                async with manager._lock:
                    if sid in manager._connections:
                        manager._connections[sid]["profile_key"] = profile_key
                        manager._connections[sid]["match_id"] = match_id
                        manager._connections[sid]["session_id"] = sid
                await websocket.send_text(json.dumps({"type": "ack", "cmd": "profile_update"}))
                continue
            if cmd == "speed":
                # client requests a speed change
                # broadcast ack; orchestrator should react in production
                await websocket.send_text(json.dumps({"type": "ack", "cmd": "speed", "speed": data.get("speed")}))
                continue
            if cmd == "restart":
                await websocket.send_text(json.dumps({"type": "ack", "cmd": "restart"}))
                continue
            # unknown commands are acknowledged as passthrough
            await websocket.send_text(json.dumps({"type": "ack", "cmd": cmd}))
    except Exception:
        # disconnect cleans up the registered socket
        await manager.disconnect(sid)
