# app/domain/single/handlers_draw.py
from __future__ import annotations

from typing import List, Optional, Tuple

from app.store.models import DrawOp
from app.transport.protocols import (
    InDrawOp,
    OutError,
    OutOpBroadcast,
    OutBudgetUpdate,
)
from app.util.timeutil import now_ts

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]


async def handle_single_draw_op(*, app, room_code: str, pid: Optional[str], msg: InDrawOp) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []
    if header.mode != "SINGLE":
        return [], []
    if header.state != "IN_ROUND":
        return [OutError(code="BAD_STATE", message=f"Cannot draw in state {header.state}")], []

    game = await repo.get_game(room_code)
    if game.get("phase") != "DRAW":
        return [OutError(code="BAD_PHASE", message="Not in DRAW phase")], []

    drawer_pid = game.get("drawer_pid") or ""
    if drawer_pid != pid:
        return [OutError(code="NOT_DRAWER", message="Only drawer can draw")], []

    strokes_left = int(game.get("strokes_left") or 0)
    if strokes_left <= 0:
        return [OutError(code="STROKE_LIMIT", message="No strokes left")], []

    strokes_left -= 1
    await repo.set_game_fields(room_code, strokes_left=strokes_left)

    op = DrawOp(
        t=msg.op.get("t", "line"),
        p=msg.op.get("p", msg.op),
        ts=ts,
        by=pid,
    )

    await repo.append_op_single(room_code, op)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    budget_ev = OutBudgetUpdate(budget={"stroke_remaining": strokes_left})
    return [budget_ev], [OutOpBroadcast(op=op.model_dump(), canvas=None, by=pid), budget_ev]
