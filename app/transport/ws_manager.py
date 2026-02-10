# app/transport/ws_manager.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, Any

from fastapi import WebSocket


@dataclass
class Conn:
    pid: str
    ws: WebSocket


class WSManager:
    """
    In-memory connection registry.
    - room_code -> pid -> websocket
    Transport-only: no Redis, no domain rules.
    """
    def __init__(self) -> None:
        self._rooms: Dict[str, Dict[str, Conn]] = {}
        self._lock = asyncio.Lock()

    async def add(self, room_code: str, pid: str, ws: WebSocket) -> None:
        async with self._lock:
            self._rooms.setdefault(room_code, {})[pid] = Conn(pid=pid, ws=ws)

    async def replace_pid(self, room_code: str, old_pid: str, new_pid: str, ws: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.setdefault(room_code, {})
            if old_pid in room:
                room.pop(old_pid, None)
            room[new_pid] = Conn(pid=new_pid, ws=ws)

    async def remove(self, room_code: str, pid: str) -> None:
        async with self._lock:
            room = self._rooms.get(room_code)
            if not room:
                return
            room.pop(pid, None)
            if not room:
                self._rooms.pop(room_code, None)

    async def send_to_pid(self, room_code: str, pid: str, event: dict) -> None:
        async with self._lock:
            room = self._rooms.get(room_code, {})
            conn = room.get(pid)
        if conn is None:
            return
        await conn.ws.send_json(event)

    async def broadcast(self, room_code: str, event: dict, exclude_pid: Optional[str] = None) -> None:
        # copy conns under lock, send outside lock
        async with self._lock:
            room = self._rooms.get(room_code, {})
            conns = list(room.values())

        for c in conns:
            if exclude_pid and c.pid == exclude_pid:
                continue
            try:
                await c.ws.send_json(event)
            except Exception:
                # if a socket is dead, ignore; ws.py will cleanup on disconnect
                pass

    async def close_pid(self, room_code: str, pid: str, code: int = 4000, reason: str = "kicked") -> None:
        """
        Close a specific player's websocket and remove from registry.
        """
        async with self._lock:
            room = self._rooms.get(room_code, {})
            conn = room.get(pid)
        if conn is None:
            return
        try:
            await conn.ws.close(code=code)
        except Exception:
            pass
        await self.remove(room_code, pid)

    async def room_size(self, room_code: str) -> int:
        async with self._lock:
            return len(self._rooms.get(room_code, {}))
