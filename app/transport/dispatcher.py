# app/transport/dispatcher.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

from pydantic import ValidationError

from app.transport.protocols import (
    parse_incoming,
    OutError,
    OutgoingEvent,
    InCreateRoom,
    InJoin,
    InLeave,
    InHeartbeat,
    InSnapshot,
    InSetTeam, InStartRolePick
)
from app.domain.lifecycle.handlers import (
    handle_create_room,
    handle_join,
    handle_leave,
    handle_heartbeat,
    handle_snapshot,
)

from app.domain.lobby.handlers import handle_set_team, handle_start_role_pick

DispatchResult = Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]
# (to_sender_events, to_room_events), each event is JSON dict


async def dispatch_message(
    *,
    app,
    room_code: str,
    pid: Optional[str],
    raw: Dict[str, Any],
) -> DispatchResult:
    """
    Transport layer calls this.
    - Parses + validates raw JSON
    - Routes to the correct domain handler
    - Returns (to_sender, to_room) events as JSON dicts

    NOTE: This file contains NO Redis key usage and NO game rules.
    """
    try:
        msg = parse_incoming(raw)
    except ValidationError as e:
        err = OutError(code="BAD_MESSAGE", message=str(e)).model_dump()
        return [err], []

    # ---- Lifecycle routing only (Slice 1) ----
    if isinstance(msg, InCreateRoom):
        to_sender, to_room = await handle_create_room(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InJoin):
        to_sender, to_room = await handle_join(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InLeave):
        to_sender, to_room = await handle_leave(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InHeartbeat):
        to_sender, to_room = await handle_heartbeat(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InSnapshot):
        to_sender, to_room = await handle_snapshot(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)
    #Lobby
    if isinstance(msg, InSetTeam):
        to_sender, to_room = await handle_set_team(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InStartRolePick):
        to_sender, to_room = await handle_start_role_pick(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)


    # If protocol exists but we didn't route it yet:
    err = OutError(code="NOT_IMPLEMENTED", message=f"Handler not implemented for type={msg.type}").model_dump()
    return [err], []


def _dump(events: List[OutgoingEvent]) -> List[Dict[str, Any]]:
    """
    Convert pydantic events -> JSON dicts.
    """
    return [e.model_dump() for e in events]
