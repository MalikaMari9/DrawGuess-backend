from __future__ import annotations

from typing import Any, Dict, Optional

from app.domain.common.validation import is_drawer
from .handlers_common import Result, auto_advance_vs_phase
from app.domain.vs.rules import SABOTAGE_COOLDOWN_SEC, SABOTAGE_COST_STROKES, SABOTAGE_DISABLE_LAST_SEC
from app.store.models import DrawOp
from app.transport.protocols import OutBudgetUpdate, OutError, OutOpBroadcast, OutSabotageUsed, InSabotage
from app.util.timeutil import now_ts


async def handle_vs_sabotage(*, app, room_code: str, pid: Optional[str], msg: InSabotage) -> Result:
    """
    Handle sabotage in VS mode.
    Drawers can sabotage opponent's canvas at cost of 1 stroke.
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
        return [OutError(code="BAD_STATE", message=f"Cannot sabotage in state {header.state}")], []

    game = await repo.get_game(room_code)
    if game.get("phase") != "DRAW":
        return [OutError(code="BAD_PHASE", message="Sabotage is only allowed in DRAW phase")], []

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

    if not is_drawer(player):
        return [OutError(code="NOT_DRAWER", message="Only drawers can sabotage")], []

    if player.team is None:
        return [OutError(code="NO_TEAM", message="Player has no team")], []

    if player.team == msg.target:
        return [OutError(code="INVALID_TARGET", message="Cannot sabotage own team")], []

    if draw_end_at and ts >= (draw_end_at - SABOTAGE_DISABLE_LAST_SEC):
        return [OutError(code="SABOTAGE_BLOCKED", message="Sabotage disabled in last 30 seconds of draw window")], []

    raw_op = msg.op or {}
    op_data: Dict[str, Any] = dict(raw_op)
    nested = raw_op.get("p")
    if isinstance(nested, dict):
        op_data.update(nested)
    op_data.pop("p", None)
    op_type = op_data.get("t", "line")

    if op_type not in ["line", "circle"]:
        return [OutError(code="INVALID_SABOTAGE_OP", message="Sabotage operation must be 'line' or 'circle'")], []

    op_payload: Dict[str, Any] = dict(op_data)
    op_payload["pid"] = pid
    op_payload.setdefault("tool", op_type)
    op_payload["sab"] = 1

    if op_type == "line":
        pts = op_payload.get("pts", [])
        if not isinstance(pts, list) or len(pts) < 2:
            return [OutError(code="INVALID_SABOTAGE", message="Sabotage line requires at least 2 points")], []
    elif op_type == "circle":
        if op_payload.get("cx") is None or op_payload.get("cy") is None or op_payload.get("r") is None:
            return [OutError(code="INVALID_SABOTAGE", message="Sabotage circle requires cx, cy and r")], []

    new_cooldown_until = ts + SABOTAGE_COOLDOWN_SEC
    ok, reason, cooldown_until, _remaining = await repo.use_sabotage(
        room_code,
        player.team,
        cost=SABOTAGE_COST_STROKES,
        now_ts=ts,
        cooldown_until=new_cooldown_until,
    )
    if not ok:
        if reason == "COOLDOWN":
            return [OutError(code="SABOTAGE_BLOCKED", message="Sabotage on cooldown")], []
        return [OutError(code="INSUFFICIENT_BUDGET", message="Not enough strokes for sabotage")], []

    draw_op = DrawOp(
        t=op_type,
        p=op_payload,
        ts=ts,
        by=pid,
    )

    await repo.append_op_vs(room_code, msg.target, draw_op)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    budget_after = await repo.get_budget(room_code)
    to_room = [
        OutOpBroadcast(op=draw_op.model_dump(), canvas=msg.target, by=pid),
        OutSabotageUsed(by=pid, target=msg.target, cooldown_until=cooldown_until),
        OutBudgetUpdate(budget=budget_after),
    ]

    return [], to_room
