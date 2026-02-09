# app/domain/vs/handlers_draw.py
from __future__ import annotations

from typing import Any, Dict, Optional

from app.domain.common.validation import is_drawer
from .handlers_common import Result
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

    if header.state != "IN_ROUND":
        return [OutError(code="BAD_STATE", message=f"Cannot draw in state {header.state}")], []

    game = await repo.get_game(room_code)
    if game.get("phase") != "DRAW":
        return [OutError(code="BAD_PHASE", message="Not in DRAW phase")], []

    player = await repo.get_player(room_code, pid)
    if player is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found")], []

    # Determine which team's canvas this is for
    canvas = msg.canvas
    if canvas is None:
        # Infer from player's team
        canvas = player.team
        if canvas is None:
            return [OutError(code="NO_TEAM", message="Player has no team")], []

    # Check if player is drawer for this team
    if not is_drawer(player, canvas):
        return [OutError(code="NOT_DRAWER", message="Only drawer can draw")], []

    # Check budget
    budget = await repo.get_budget(room_code)
    team_budget_key = canvas
    remaining = budget.get(team_budget_key, 0)

    if remaining <= 0:
        return [OutError(code="NO_BUDGET", message="No strokes remaining for this phase")], []

    # Parse draw operation (compact format as per spec)
    # Example line op:
    # {"t":"line","pid":"p_x","tool":"line","c":"#000","w":3,"pts":[[x,y],...],"sab":0}
    op_data = msg.op or {}
    op_type = op_data.get("t", "line")

    # Validate operation type (only line and circle tools allowed)
    if op_type not in ["line", "circle"]:
        return [
            OutError(
                code="INVALID_OP",
                message=f"Invalid operation type: {op_type}. Only 'line' and 'circle' are allowed.",
            )
        ], []

    # Normalize/augment payload
    op_payload: Dict[str, Any] = dict(op_data)
    op_payload["pid"] = pid  # authoritative server pid
    op_payload.setdefault("tool", op_type)
    op_payload.setdefault("sab", 0)

    if op_type == "line":
        # Line tool: validate pts array
        pts = op_payload.get("pts", [])
        if not isinstance(pts, list) or len(pts) < 2:
            return [OutError(code="INVALID_LINE", message="Line operation requires at least 2 points")], []

        # Auto-split check: prevent abuse by splitting long strokes
        start_ts = op_payload.get("start_ts", ts)
        # Flatten pts into list of dicts for compatibility with should_auto_split_stroke
        points_for_check = [{"x": p[0], "y": p[1]} for p in pts if isinstance(p, (list, tuple)) and len(p) == 2]
        if should_auto_split_stroke(points_for_check, start_ts, ts):
            # Server-side enforcement: reject stroke and consume budget to prevent bypass
            await repo.set_budget_fields(room_code, **{team_budget_key: max(0, remaining - 1)})
            return [
                OutError(
                    code="STROKE_TOO_LONG",
                    message="Stroke too long (exceeds duration or point limit). Budget consumed.",
                )
            ], []

    elif op_type == "circle":
        # Circle tool: validate center and radius
        cx = op_payload.get("cx")
        cy = op_payload.get("cy")
        r = op_payload.get("r")
        if cx is None or cy is None or r is None:
            return [OutError(code="INVALID_CIRCLE", message="Circle operation requires 'cx', 'cy' and 'r'")], []

        # Validate radius is reasonable (prevent abuse)
        if not isinstance(r, (int, float)) or r < 0 or r > 1000:
            return [OutError(code="INVALID_RADIUS", message="Circle radius must be between 0 and 1000")], []

    # Create DrawOp with compact payload
    draw_op = DrawOp(
        t=op_type,
        p=op_payload,
        ts=ts,
        by=pid,
    )

    # Consume budget
    await repo.set_budget_fields(room_code, **{team_budget_key: remaining - 1})

    # Store operation
    await repo.append_op_vs(room_code, canvas, draw_op)

    # Update activity
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    # Broadcast to room
    budget_after = await repo.get_budget(room_code)
    return [], [
        OutOpBroadcast(op=draw_op.model_dump(), canvas=canvas, by=pid),
        OutBudgetUpdate(budget=budget_after),
    ]
