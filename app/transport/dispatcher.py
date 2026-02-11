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
    InReconnect,
    InSetTeam,
    InStartRolePick,
    InAssignRoles,
    InStartRound,
    InSetRoundConfig,
    InStartGame,
    InDrawOp,
    InGuess,
    InPhaseTick,
    InSabotage,
    InVoteNext,
    InModeration,
    InEndRound,
)
from app.domain.lifecycle.handlers import (
    handle_create_room,
    handle_join,
    handle_leave,
    handle_heartbeat,
    handle_snapshot,
    handle_reconnect,
)

from app.domain.lobby.handlers import handle_set_team, handle_start_role_pick
from app.domain.vs.handlers import (
    handle_vs_role_pick,
    handle_vs_start_round,
    handle_vs_draw_op,
    handle_vs_guess,
    handle_vs_phase_tick,
    handle_vs_sabotage,
    handle_vs_vote_next,
)
from app.domain.moderation.handlers import handle_moderation
from app.domain.single.handlers import (
    handle_single_set_round_config,
    handle_single_start_game,
    handle_single_draw_op,
    handle_single_guess,
    handle_single_phase_tick,
    handle_single_vote_next,
)
from app.domain.common.end_round import handle_end_round
from app.domain.common.validation import is_muted
from app.util.timeutil import now_ts

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
    except (ValidationError, ValueError) as e:
        err = OutError(code="BAD_MESSAGE", message=str(e)).model_dump()
        return [err], []

    # If player is kicked, block all non-join messages
    if pid and not isinstance(msg, (InCreateRoom, InJoin, InReconnect)):
        repo = app.state.repo
        player = await repo.get_player(room_code, pid)
        if player is not None and getattr(player, "kicked", False):
            err = OutError(code="KICKED", message="You have been kicked from this room").model_dump()
            return [err], []

    # If player is muted, block all actions except heartbeat/snapshot/leave
    if pid and not isinstance(msg, (InCreateRoom, InJoin, InReconnect, InHeartbeat, InSnapshot, InLeave)):
        repo = app.state.repo
        player = await repo.get_player(room_code, pid)
        if player is not None and is_muted(player, now_ts()):
            err = OutError(code="MUTED", message="You are muted").model_dump()
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

    if isinstance(msg, InReconnect):
        to_sender, to_room = await handle_reconnect(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)
    #Lobby
    if isinstance(msg, InSetTeam):
        to_sender, to_room = await handle_set_team(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InStartRolePick):
        to_sender, to_room = await handle_start_role_pick(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InModeration):
        to_sender, to_room = await handle_moderation(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InEndRound):
        to_sender, to_room = await handle_end_round(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    # ---- SINGLE: GM config / start ----
    if isinstance(msg, InSetRoundConfig):
        to_sender, to_room = await handle_single_set_round_config(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InStartGame):
        to_sender, to_room = await handle_single_start_game(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    # ---- VS Mode routing ----
    if isinstance(msg, InAssignRoles):
        to_sender, to_room = await handle_vs_role_pick(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    if isinstance(msg, InStartRound):
        to_sender, to_room = await handle_vs_start_round(app=app, room_code=room_code, pid=pid, msg=msg)
        return _dump(to_sender), _dump(to_room)

    # Route draw_op, guess, phase_tick, sabotage based on room mode
    # For now, route to VS handlers if mode is VS (could be improved with mode check)
    if isinstance(msg, InDrawOp):
        # Check room mode to route appropriately
        repo = app.state.repo
        header = await repo.get_room_header(room_code)
        if header and header.mode == "VS":
            to_sender, to_room = await handle_vs_draw_op(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        if header and header.mode == "SINGLE":
            to_sender, to_room = await handle_single_draw_op(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        err = OutError(code="NOT_IMPLEMENTED", message="draw_op only for VS/SINGLE rooms").model_dump()
        return [err], []

    if isinstance(msg, InGuess):
        repo = app.state.repo
        header = await repo.get_room_header(room_code)
        if header and header.mode == "VS":
            to_sender, to_room = await handle_vs_guess(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        if header and header.mode == "SINGLE":
            to_sender, to_room = await handle_single_guess(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        err = OutError(code="NOT_IMPLEMENTED", message="guess only for VS/SINGLE rooms").model_dump()
        return [err], []

    if isinstance(msg, InPhaseTick):
        repo = app.state.repo
        header = await repo.get_room_header(room_code)
        if header and header.mode == "VS":
            to_sender, to_room = await handle_vs_phase_tick(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        if header and header.mode == "SINGLE":
            to_sender, to_room = await handle_single_phase_tick(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        err = OutError(code="NOT_IMPLEMENTED", message="phase_tick only for VS/SINGLE rooms").model_dump()
        return [err], []

    if isinstance(msg, InSabotage):
        repo = app.state.repo
        header = await repo.get_room_header(room_code)
        if header and header.mode == "VS":
            to_sender, to_room = await handle_vs_sabotage(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        err = OutError(code="NOT_IMPLEMENTED", message="Sabotage only for VS mode").model_dump()
        return [err], []

    if isinstance(msg, InVoteNext):
        repo = app.state.repo
        header = await repo.get_room_header(room_code)
        if header and header.mode == "VS":
            to_sender, to_room = await handle_vs_vote_next(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        if header and header.mode == "SINGLE":
            to_sender, to_room = await handle_single_vote_next(app=app, room_code=room_code, pid=pid, msg=msg)
            return _dump(to_sender), _dump(to_room)
        err = OutError(code="NOT_IMPLEMENTED", message="vote_next only for VS/SINGLE rooms").model_dump()
        return [err], []

    # If protocol exists but we didn't route it yet:
    err = OutError(code="NOT_IMPLEMENTED", message=f"Handler not implemented for type={msg.type}").model_dump()
    return [err], []


def _dump(events: List[OutgoingEvent]) -> List[Dict[str, Any]]:
    """
    Convert pydantic events -> JSON dicts.
    """
    return [e.model_dump() for e in events]
