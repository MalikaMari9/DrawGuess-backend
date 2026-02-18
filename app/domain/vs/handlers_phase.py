from __future__ import annotations

from typing import Optional

from .handlers_common import Result, auto_advance_vs_phase
from app.transport.protocols import OutError, InPhaseTick
from app.util.timeutil import now_ts


async def handle_vs_phase_tick(*, app, room_code: str, pid: Optional[str], msg: InPhaseTick) -> Result:
    """
    Advance phase in VS mode based on window timers.
    """
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []

    if header.mode != "VS":
        return [OutError(code="NOT_VS", message="This handler is for VS mode only")], []

    events = await auto_advance_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)
    if events:
        return list(events), events

    return [], []
