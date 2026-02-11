# app/domain/single/handlers_phase.py
from __future__ import annotations

from typing import List, Optional, Tuple

from app.transport.protocols import InPhaseTick, OutError, OutPhaseChanged
from app.util.timeutil import now_ts
from app.domain.lifecycle.handlers import _auto_expire_single_round

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]


async def handle_single_phase_tick(*, app, room_code: str, pid: Optional[str], msg: InPhaseTick) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []
    if header.mode != "SINGLE":
        return [OutError(code="NOT_SINGLE", message="This handler is for SINGLE mode only")], []
    if header.state != "IN_ROUND":
        return [OutError(code="BAD_STATE", message=f"Cannot phase_tick in state {header.state}")], []

    timeout_events = await _auto_expire_single_round(repo=repo, room_code=room_code, header=header, ts=ts)
    if timeout_events:
        return [OutError(code="ROUND_ENDED", message="Round timed out")], timeout_events

    player = await repo.get_player(room_code, pid)
    if not player or getattr(player, "role", None) != "gm":
        return [OutError(code="NOT_GM", message="Only GM can advance phases")], []

    game = await repo.get_game(room_code)
    phase = game.get("phase") or "DRAW"

    if phase == "DRAW":
        await repo.set_game_fields(room_code, phase="GUESS")
        new_phase = "GUESS"
    elif phase == "GUESS":
        cfg = await repo.get_round_config(room_code)
        stroke_limit = int(cfg.get("stroke_limit") or 0)
        await repo.set_game_fields(room_code, phase="DRAW", strokes_left=stroke_limit)
        new_phase = "DRAW"
    else:
        return [OutError(code="BAD_PHASE", message=f"Cannot tick from phase {phase}")], []

    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    return [], [OutPhaseChanged(phase=new_phase, round_no=header.round_no)]
