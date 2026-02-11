# app/domain/vs/handlers_sabotage.py
from __future__ import annotations

from typing import Any, Dict, Optional

from app.domain.common.validation import is_drawer
from .handlers_common import Result
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

    if header.state != "IN_ROUND":
        return [OutError(code="BAD_STATE", message=f"Cannot sabotage in state {header.state}")], []

    # Sabotage only allowed in DRAW phase
    game = await repo.get_game(room_code)
    if game.get("phase") != "DRAW":
        return [OutError(code="BAD_PHASE", message="Sabotage is only allowed in DRAW phase")], []

    player = await repo.get_player(room_code, pid)
    if player is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found")], []

    if not is_drawer(player):
        return [OutError(code="NOT_DRAWER", message="Only drawers can sabotage")], []

    if player.team is None:
        return [OutError(code="NO_TEAM", message="Player has no team")], []

    # Cannot sabotage own team
    if player.team == msg.target:
        return [OutError(code="INVALID_TARGET", message="Cannot sabotage own team")], []

    # Check cooldown
    round_cfg = await repo.get_round_config(room_code)
    round_start_ts = round_cfg.get("round_started_at", ts)
    round_duration_sec = round_cfg.get("time_limit_sec", 300)

    # Only enforce "last 30 seconds" here; cooldown is handled atomically in Redis
    if ts >= (round_start_ts + round_duration_sec - SABOTAGE_DISABLE_LAST_SEC):
        return [OutError(code="SABOTAGE_BLOCKED", message="Sabotage disabled in last 30 seconds of round")], []

    # Validate sabotage operation (must be a valid draw operation: line or circle)
    op_data = msg.op or {}
    op_type = op_data.get("t", "line")

    # Sabotage can use line or circle tool
    if op_type not in ["line", "circle"]:
        return [OutError(code="INVALID_SABOTAGE_OP", message="Sabotage operation must be 'line' or 'circle'")], []

    # Normalize/augment payload (same compact format as draw_op)
    op_payload: Dict[str, Any] = dict(op_data)
    op_payload["pid"] = pid
    op_payload.setdefault("tool", op_type)
    op_payload["sab"] = 1  # mark as sabotage stroke

    if op_type == "line":
        pts = op_payload.get("pts", [])
        if not isinstance(pts, list) or len(pts) < 2:
            return [OutError(code="INVALID_SABOTAGE", message="Sabotage line requires at least 2 points")], []
    elif op_type == "circle":
        if op_payload.get("cx") is None or op_payload.get("cy") is None or op_payload.get("r") is None:
            return [OutError(code="INVALID_SABOTAGE", message="Sabotage circle requires cx, cy and r")], []

    # Atomic budget+cooldown check/update
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

    # Create sabotage operation (one stroke on opponent's canvas)
    draw_op = DrawOp(
        t=op_type,
        p=op_payload,
        ts=ts,
        by=pid,
    )

    # Store on target team's canvas (opponent's canvas)
    await repo.append_op_vs(room_code, msg.target, draw_op)

    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    budget_after = await repo.get_budget(room_code)
    return [], [
        OutOpBroadcast(op=draw_op.model_dump(), canvas=msg.target, by=pid),
        OutSabotageUsed(by=pid, target=msg.target, cooldown_until=cooldown_until),
        OutBudgetUpdate(budget=budget_after),
    ]
