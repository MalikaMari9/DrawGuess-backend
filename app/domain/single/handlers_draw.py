from __future__ import annotations

from typing import List, Optional, Tuple

from app.store.models import DrawOp
from app.domain.common.ops import validate_draw_op
from app.domain.lifecycle.handlers import _auto_expire_single_game
from app.domain.vs.rules import should_auto_split_stroke
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
        return [OutError(code="NOT_SINGLE", message="This handler is for SINGLE mode only")], []
    if header.state != "IN_GAME":
        return [OutError(code="BAD_STATE", message=f"Cannot draw in state {header.state}")], []

    timeout_events = await _auto_expire_single_game(repo=repo, room_code=room_code, header=header, ts=ts)
    if timeout_events:
        return [OutError(code="GAME_ENDED", message="Game timed out")], timeout_events

    game = await repo.get_game(room_code)
    if game.get("phase") != "DRAW":
        return [OutError(code="BAD_PHASE", message="Not in DRAW phase")], []

    drawer_pid = game.get("drawer_pid") or ""
    if drawer_pid != pid:
        return [OutError(code="NOT_DRAWER", message="Only drawer can draw")], []

    strokes_left = int(game.get("strokes_left") or 0)
    if strokes_left <= 0:
        return [OutError(code="STROKE_LIMIT", message="No strokes left")], []

    op_data = msg.op or {}
    ok, op_type, err_code, err_msg = validate_draw_op(op_data)
    if not ok:
        return [OutError(code=err_code, message=err_msg)], []

    if op_type == "line":
        pts = None
        if isinstance(op_data.get("p"), dict):
            pts = op_data["p"].get("pts")
        if pts is None:
            pts = op_data.get("pts")
        pts = pts or []
        start_ts = op_data.get("start_ts", ts)
        points_for_check = [{"x": p[0], "y": p[1]} for p in pts if isinstance(p, (list, tuple)) and len(p) == 2]
        if should_auto_split_stroke(points_for_check, start_ts, ts):
            return [
                OutError(
                    code="STROKE_TOO_LONG",
                    message="Stroke too long (exceeds duration or point limit).",
                )
            ], []

    strokes_left -= 1
    await repo.set_game_fields(room_code, strokes_left=strokes_left)

    op = DrawOp(
        t=op_type,
        p=op_data.get("p", op_data),
        ts=ts,
        by=pid,
    )

    await repo.append_op_single(room_code, op)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    budget_ev = OutBudgetUpdate(budget={"stroke_remaining": strokes_left})
    return [budget_ev], [OutOpBroadcast(op=op.model_dump(), canvas=None, by=pid), budget_ev]
