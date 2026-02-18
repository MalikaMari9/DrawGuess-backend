from __future__ import annotations

from typing import Any, Dict, Optional

from app.domain.common.validation import is_drawer
from app.domain.common.ops import validate_draw_op
from .handlers_common import Result, auto_advance_vs_phase
from app.domain.vs.rules import should_auto_split_stroke
from app.store.models import DrawOp
from app.transport.protocols import OutBudgetUpdate, OutError, OutOpBroadcast, InDrawOp
from app.util.timeutil import now_ts


async def handle_vs_draw_op(*, app, room_code: str, pid: Optional[str], msg: InDrawOp) -> Result:
    """
    Handle drawing operations in VS mode.
    Enforces stroke budget and auto-splitting.
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

    if header.state != "IN_GAME":
        return [OutError(code="BAD_STATE", message=f"Cannot draw in state {header.state}")], []

    game = await repo.get_game(room_code)
    if game.get("phase") != "DRAW":
        return [OutError(code="BAD_PHASE", message="Not in DRAW phase")], []

    draw_end_at_raw = game.get("draw_end_at", 0)
    try:
        draw_end_at = int(draw_end_at_raw) if draw_end_at_raw else 0
    except (TypeError, ValueError):
        draw_end_at = 0
    if draw_end_at and ts >= draw_end_at:
        events = await auto_advance_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)
        return [OutError(code="DRAW_EXPIRED", message="Draw window ended")], events

    player = await repo.get_player(room_code, pid)
    if player is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found")], []

    canvas = msg.canvas
    if canvas is None:
        canvas = player.team
        if canvas is None:
            return [OutError(code="NO_TEAM", message="Player has no team")], []

    if not is_drawer(player, canvas):
        return [OutError(code="NOT_DRAWER", message="Only drawer can draw")], []

    raw_op = msg.op or {}
    op_data: Dict[str, Any] = dict(raw_op)
    nested = raw_op.get("p")
    if isinstance(nested, dict):
        op_data.update(nested)
    op_data.pop("p", None)
    ok, op_type, err_code, err_msg = validate_draw_op(op_data)
    if not ok:
        return [OutError(code=err_code, message=err_msg)], []

    op_payload: Dict[str, Any] = dict(op_data)
    op_payload["pid"] = pid
    op_payload.setdefault("tool", op_type)
    op_payload.setdefault("sab", 0)

    if op_type == "line":
        pts = op_payload.get("pts")
        if pts is None and isinstance(op_payload.get("p"), dict):
            pts = op_payload["p"].get("pts")
            if pts is not None:
                op_payload["pts"] = pts
        pts = pts or []
        ok, _remaining = await repo.consume_vs_stroke(room_code, canvas, cost=1)
        if not ok:
            return [OutError(code="NO_BUDGET", message="No strokes remaining for this phase")], []
        start_ts = op_payload.get("start_ts", ts)
        points_for_check = [{"x": p[0], "y": p[1]} for p in pts if isinstance(p, (list, tuple)) and len(p) == 2]
        if should_auto_split_stroke(points_for_check, start_ts, ts):
            return [
                OutError(
                    code="STROKE_TOO_LONG",
                    message="Stroke too long (exceeds duration or point limit). Budget consumed.",
                )
            ], []

    elif op_type == "circle":
        ok, _remaining = await repo.consume_vs_stroke(room_code, canvas, cost=1)
        if not ok:
            return [OutError(code="NO_BUDGET", message="No strokes remaining for this phase")], []

    draw_op = DrawOp(
        t=op_type,
        p=op_payload,
        ts=ts,
        by=pid,
    )

    await repo.append_op_vs(room_code, canvas, draw_op)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    budget_after = await repo.get_budget(room_code)
    to_room = [
        OutOpBroadcast(op=draw_op.model_dump(), canvas=canvas, by=pid),
        OutBudgetUpdate(budget=budget_after),
    ]

    return [], to_room
