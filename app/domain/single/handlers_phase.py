from __future__ import annotations

from typing import List, Optional, Tuple

from app.transport.protocols import InPhaseTick, OutError
from app.util.timeutil import now_ts
from app.domain.lifecycle.handlers import _auto_expire_single_game

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
    if header.state != "IN_GAME":
        return [], []

    tick_events = await _auto_expire_single_game(repo=repo, room_code=room_code, header=header, ts=ts)
    if tick_events:
        return list(tick_events), tick_events
    # SINGLE phase progression is lifecycle-driven; phase_tick is intentionally a no-op.
    return [], []
