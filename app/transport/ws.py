# app/transport/ws.py
from __future__ import annotations

import uuid
import ipaddress
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.settings import get_settings
from app.domain.lifecycle.handlers import handle_disconnect
from app.transport.dispatcher import dispatch_message

router = APIRouter()


def _is_private_ip(host: str) -> bool:
    """Return True if host is a private IP (192.168.x.x, 10.x.x.x, 172.16-31.x.x)."""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private
    except ValueError:
        return False


@router.websocket("/ws/{room_code}")
async def ws_room(websocket: WebSocket, room_code: str):
    settings = get_settings()

    # ---- Origin allowlist (anti cross-site WS) ----
    allowed = {o.strip() for o in settings.WS_ALLOWED_ORIGINS.split(",") if o.strip()}

    origin = websocket.headers.get("origin")
    if origin is not None:
        if origin in allowed:
            pass
        elif settings.WS_ALLOW_LAN_ORIGINS:
            # Allow LAN frontend origins like http://192.168.0.101:5173
            o = urlparse(origin)
            host = o.hostname or ""
            port = o.port
            if not (_is_private_ip(host) and port == 5173):
                await websocket.close(code=1008)  # Policy Violation
                return
        else:
            await websocket.close(code=1008)  # Policy Violation
            return

    await websocket.accept()

    pid = uuid.uuid4().hex[:10]
    wsman = websocket.app.state.wsman
    await wsman.add(room_code, pid, websocket)

    try:
        while True:
            raw = await websocket.receive_json()

            to_sender, to_room = await dispatch_message(
                app=websocket.app,
                room_code=room_code,
                pid=pid,
                raw=raw,
            )

            # unicast
            for e in to_sender:
                await websocket.send_json(e)

            # broadcast (exclude sender by default to avoid duplicates)
            for e in to_room:
                await wsman.broadcast(room_code, e, exclude_pid=pid)

    except WebSocketDisconnect:
        to_sender, to_room = await handle_disconnect(
            app=websocket.app,
            room_code=room_code,
            pid=pid,
        )

        for e in to_room:
            await wsman.broadcast(room_code, e, exclude_pid=pid)

    finally:
        await wsman.remove(room_code, pid)
