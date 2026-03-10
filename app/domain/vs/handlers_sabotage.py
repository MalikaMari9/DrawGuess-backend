from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional, Tuple

from app.domain.common.validation import is_drawer
from .handlers_common import Result, auto_advance_vs_phase
from app.store.models import DrawOp
from app.transport.protocols import (
    OutBudgetUpdate,
    OutError,
    OutOpBroadcast,
    OutSabotageUsed,
    OutSabotageState,
    InSabotage,
    InSabotageArm,
    InSabotageCancel,
)
from app.util.timeutil import now_ts

_ROOM_SABOTAGE_LOCKS: dict[str, asyncio.Lock] = {}
SABOTAGE_ARM_DURATION_SEC = 10


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _team_or_none(value: Any) -> Optional[str]:
    if value in ("A", "B"):
        return str(value)
    return None


def _armed_state(game: Dict[str, Any], ts: int) -> Tuple[bool, str, Optional[str], Optional[str], int]:
    by = str(game.get("sabotage_armed_by") or "")
    from_team = _team_or_none(game.get("sabotage_armed_team"))
    target = _team_or_none(game.get("sabotage_target_team"))
    armed_until = _int(game.get("sabotage_armed_until"), 0)
    active = bool(by and from_team and target and armed_until > ts)
    return active, by, from_team, target, armed_until


def _inactive_sabotage_state(reason: str) -> OutSabotageState:
    return OutSabotageState(
        active=False,
        by="",
        from_team=None,
        target=None,
        armed_until=0,
        reason=reason,
    )


async def _clear_armed_fields(*, repo, room_code: str) -> None:
    await repo.set_game_fields(
        room_code,
        sabotage_armed_by="",
        sabotage_armed_team="",
        sabotage_target_team="",
        sabotage_armed_until=0,
    )


async def _clear_expired_armed_state(
    *,
    repo,
    room_code: str,
    game: Dict[str, Any],
    ts: int,
) -> list[OutSabotageState]:
    active, by, from_team, target, armed_until = _armed_state(game, ts)
    if active:
        return []
    if not by and not from_team and not target and armed_until <= 0:
        return []
    if armed_until > ts:
        return []
    await _clear_armed_fields(repo=repo, room_code=room_code)
    return [_inactive_sabotage_state("EXPIRED")]


async def clear_vs_sabotage_if_armed_by(
    *,
    app,
    room_code: str,
    pid: str,
    reason: str = "CANCELLED",
) -> list[OutSabotageState]:
    lock = _ROOM_SABOTAGE_LOCKS.setdefault(room_code, asyncio.Lock())
    async with lock:
        repo = app.state.repo
        header = await repo.get_room_header(room_code)
        if header is None or header.mode != "VS":
            return []

        ts = now_ts()
        game = await repo.get_game(room_code)
        active, by, _from_team, _target, _armed_until = _armed_state(game, ts)
        if not active or by != pid:
            return []

        await _clear_armed_fields(repo=repo, room_code=room_code)
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")
        return [_inactive_sabotage_state(reason)]


async def handle_vs_sabotage_arm(*, app, room_code: str, pid: Optional[str], msg: InSabotageArm) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    lock = _ROOM_SABOTAGE_LOCKS.setdefault(room_code, asyncio.Lock())
    async with lock:
        repo = app.state.repo
        ts = now_ts()

        header = await repo.get_room_header(room_code)
        if header is None:
            return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []

        if header.mode != "VS":
            return [OutError(code="NOT_VS", message="This handler is for VS mode only")], []

        if header.state != "IN_GAME":
            return [OutError(code="BAD_STATE", message=f"Cannot arm sabotage in state {header.state}")], []

        game = await repo.get_game(room_code)
        expiry_events = await _clear_expired_armed_state(repo=repo, room_code=room_code, game=game, ts=ts)
        if expiry_events:
            game = await repo.get_game(room_code)

        if game.get("phase") != "DRAW":
            to_sender: list[Any] = [*expiry_events, OutError(code="BAD_PHASE", message="Sabotage is only allowed in DRAW phase")]
            return to_sender, list(expiry_events)

        draw_end_at = _int(game.get("draw_end_at"), 0)
        if draw_end_at and ts >= draw_end_at:
            events = await auto_advance_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)
            to_sender = [*expiry_events, OutError(code="DRAW_EXPIRED", message="Draw window ended")]
            return to_sender, [*expiry_events, *events]

        player = await repo.get_player(room_code, pid)
        if player is None:
            to_sender = [*expiry_events, OutError(code="PLAYER_NOT_FOUND", message="Player not found")]
            return to_sender, list(expiry_events)

        if not is_drawer(player):
            to_sender = [*expiry_events, OutError(code="NOT_DRAWER", message="Only drawers can sabotage")]
            return to_sender, list(expiry_events)

        if player.team is None:
            to_sender = [*expiry_events, OutError(code="NO_TEAM", message="Player has no team")]
            return to_sender, list(expiry_events)

        sabotage_used = game.get("sabotage_used") or {}
        if not isinstance(sabotage_used, dict):
            sabotage_used = {}
        if bool(sabotage_used.get(player.team)):
            to_sender = [
                *expiry_events,
                OutError(code="SABOTAGE_USED", message="Your team already used sabotage in this game"),
            ]
            return to_sender, list(expiry_events)

        active, by, from_team, target, armed_until = _armed_state(game, ts)
        if active:
            if by == pid and from_team == player.team and target in ("A", "B"):
                armed_ev = OutSabotageState(
                    active=True,
                    by=by,
                    from_team=from_team,
                    target=target,
                    armed_until=armed_until,
                    reason="ARMED",
                )
                return [*expiry_events, armed_ev], [*expiry_events, armed_ev]
            to_sender = [*expiry_events, OutError(code="SABOTAGE_BUSY", message="Another sabotage is already armed")]
            return to_sender, list(expiry_events)

        from_team = player.team
        target = "B" if from_team == "A" else "A"
        armed_until = ts + SABOTAGE_ARM_DURATION_SEC
        await repo.set_game_fields(
            room_code,
            sabotage_armed_by=pid,
            sabotage_armed_team=from_team,
            sabotage_target_team=target,
            sabotage_armed_until=armed_until,
        )
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")

        armed_ev = OutSabotageState(
            active=True,
            by=pid,
            from_team=from_team,
            target=target,
            armed_until=armed_until,
            reason="ARMED",
        )
        return [*expiry_events, armed_ev], [*expiry_events, armed_ev]


async def handle_vs_sabotage_cancel(*, app, room_code: str, pid: Optional[str], msg: InSabotageCancel) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    lock = _ROOM_SABOTAGE_LOCKS.setdefault(room_code, asyncio.Lock())
    async with lock:
        repo = app.state.repo
        ts = now_ts()

        header = await repo.get_room_header(room_code)
        if header is None:
            return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []

        if header.mode != "VS":
            return [OutError(code="NOT_VS", message="This handler is for VS mode only")], []

        game = await repo.get_game(room_code)
        expiry_events = await _clear_expired_armed_state(repo=repo, room_code=room_code, game=game, ts=ts)
        if expiry_events:
            game = await repo.get_game(room_code)

        active, by, _from_team, _target, _armed_until = _armed_state(game, ts)
        if not active:
            return list(expiry_events), list(expiry_events)

        if by != pid:
            to_sender = [*expiry_events, OutError(code="NOT_ARMED_BY_YOU", message="Only the arming drawer can cancel")]
            return to_sender, list(expiry_events)

        await _clear_armed_fields(repo=repo, room_code=room_code)
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")
        clear_ev = _inactive_sabotage_state("CANCELLED")
        return [*expiry_events, clear_ev], [*expiry_events, clear_ev]


async def handle_vs_sabotage(*, app, room_code: str, pid: Optional[str], msg: InSabotage) -> Result:
    """
    Handle sabotage in VS mode.
    Drawers can sabotage opponent's canvas at cost of 1 stroke.
    Each team can sabotage at most once per game.
    """
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    lock = _ROOM_SABOTAGE_LOCKS.setdefault(room_code, asyncio.Lock())
    async with lock:
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
        expiry_events = await _clear_expired_armed_state(repo=repo, room_code=room_code, game=game, ts=ts)
        if expiry_events:
            game = await repo.get_game(room_code)
        if game.get("phase") != "DRAW":
            return [*expiry_events, OutError(code="BAD_PHASE", message="Sabotage is only allowed in DRAW phase")], list(expiry_events)

        draw_end_at_raw = game.get("draw_end_at", 0)
        try:
            draw_end_at = int(draw_end_at_raw) if draw_end_at_raw else 0
        except (TypeError, ValueError):
            draw_end_at = 0
        if draw_end_at and ts >= draw_end_at:
            events = await auto_advance_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)
            return [*expiry_events, OutError(code="DRAW_EXPIRED", message="Draw window ended")], [*expiry_events, *events]

        player = await repo.get_player(room_code, pid)
        if player is None:
            return [*expiry_events, OutError(code="PLAYER_NOT_FOUND", message="Player not found")], list(expiry_events)

        if not is_drawer(player):
            return [*expiry_events, OutError(code="NOT_DRAWER", message="Only drawers can sabotage")], list(expiry_events)

        if player.team is None:
            return [*expiry_events, OutError(code="NO_TEAM", message="Player has no team")], list(expiry_events)

        if player.team == msg.target:
            return [*expiry_events, OutError(code="INVALID_TARGET", message="Cannot sabotage own team")], list(expiry_events)

        armed_active, armed_by, armed_from_team, armed_target, _armed_until = _armed_state(game, ts)
        if not armed_active:
            return [*expiry_events, OutError(code="SABOTAGE_NOT_ARMED", message="Arm sabotage first")], list(expiry_events)
        if armed_by != pid or armed_from_team != player.team or armed_target != msg.target:
            return [
                *expiry_events,
                OutError(code="SABOTAGE_NOT_ARMED", message="Your team does not have a valid armed sabotage"),
            ], list(expiry_events)

        sabotage_used = game.get("sabotage_used") or {}
        if not isinstance(sabotage_used, dict):
            sabotage_used = {}
        if bool(sabotage_used.get(player.team)):
            return [
                *expiry_events,
                OutError(code="SABOTAGE_USED", message="Your team already used sabotage in this game"),
            ], list(expiry_events)

        raw_op = msg.op or {}
        op_data: Dict[str, Any] = dict(raw_op)
        nested = raw_op.get("p")
        if isinstance(nested, dict):
            op_data.update(nested)
        op_data.pop("p", None)
        op_type = op_data.get("t", "line")

        if op_type not in ["line", "circle"]:
            return [
                *expiry_events,
                OutError(code="INVALID_SABOTAGE_OP", message="Sabotage operation must be 'line' or 'circle'"),
            ], list(expiry_events)

        op_payload: Dict[str, Any] = dict(op_data)
        op_payload["pid"] = pid
        op_payload.setdefault("tool", op_type)
        op_payload["sab"] = 1

        if op_type == "line":
            pts = op_payload.get("pts", [])
            if not isinstance(pts, list) or len(pts) < 2:
                return [
                    *expiry_events,
                    OutError(code="INVALID_SABOTAGE", message="Sabotage line requires at least 2 points"),
                ], list(expiry_events)
        elif op_type == "circle":
            if op_payload.get("cx") is None or op_payload.get("cy") is None or op_payload.get("r") is None:
                return [
                    *expiry_events,
                    OutError(code="INVALID_SABOTAGE", message="Sabotage circle requires cx, cy and r"),
                ], list(expiry_events)

        ok, _remaining = await repo.consume_vs_stroke(room_code, player.team, cost=1)
        if not ok:
            return [
                *expiry_events,
                OutError(code="INSUFFICIENT_BUDGET", message="Not enough strokes for sabotage"),
            ], list(expiry_events)

        sabotage_used[player.team] = True
        await repo.set_game_fields(
            room_code,
            sabotage_used=sabotage_used,
            sabotage_armed_by="",
            sabotage_armed_team="",
            sabotage_target_team="",
            sabotage_armed_until=0,
        )

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
        budget_ev = OutBudgetUpdate(budget=budget_after)
        sabotage_ev = OutSabotageUsed(by=pid, target=msg.target, cooldown_until=0)
        op_ev = OutOpBroadcast(op=draw_op.model_dump(), canvas=msg.target, by=pid)
        clear_ev = _inactive_sabotage_state("USED")
        transition_events = await auto_advance_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)
        to_room = [
            *expiry_events,
            op_ev,
            sabotage_ev,
            budget_ev,
            clear_ev,
            *transition_events,
        ]

        # Sender also receives op_broadcast so sabotage rendering is consistent for every client.
        return [*expiry_events, op_ev, sabotage_ev, budget_ev, clear_ev, *transition_events], to_room
