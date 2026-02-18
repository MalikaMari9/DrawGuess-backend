from __future__ import annotations

from typing import Optional

from app.domain.vs.rules import validate_vs_start_conditions
from app.transport.protocols import (
    OutBudgetUpdate,
    OutError,
    OutPhaseChanged,
    OutRoomSnapshot,
    OutRoomStateChanged,
    InStartGame,
)
from app.util.timeutil import now_ts



async def _snapshot_for(app, room_code: str, *, viewer_pid: Optional[str]) -> OutRoomSnapshot:
    from app.domain.lifecycle.handlers import _build_snapshot
    header = await app.state.repo.get_room_header(room_code)
    mode = header.mode if header else "VS"
    return await _build_snapshot(app, room_code, mode, viewer_pid=viewer_pid, redact_secret=True)


async def handle_vs_start_game(*, app, room_code: str, pid: Optional[str], msg: InStartGame):
    """
    Start a VS mode game (round 1) after config is set.
    Game begins with DRAW phase.
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

    if header.state != "CONFIG":
        return [OutError(code="BAD_STATE", message=f"Cannot start game in state {header.state}")], []

    if header.gm_pid != pid:
        return [OutError(code="NOT_GM", message="Only GameMaster can start games")], []

    round_cfg = await repo.get_round_config(room_code)
    secret = (round_cfg.get("secret_word") or "").strip()
    draw_window_sec = int(round_cfg.get("draw_window_sec") or 0)
    guess_window_sec = int(round_cfg.get("guess_window_sec") or 0)
    stroke_limit = int(round_cfg.get("strokes_per_phase") or 0)
    max_rounds = int(round_cfg.get("max_rounds") or 0)

    if not secret or draw_window_sec <= 0 or guess_window_sec <= 0 or stroke_limit <= 0 or max_rounds <= 0:
        return [OutError(code="CONFIG_MISSING", message="GM must set VS config before starting")], []

    players = await repo.list_players(room_code)
    teams = {
        "A": await repo.get_team_members(room_code, "A"),
        "B": await repo.get_team_members(room_code, "B"),
    }

    can_start, error = validate_vs_start_conditions(players, teams, gm_pid=header.gm_pid)
    if not can_start:
        return [OutError(code="START_FAILED", message=error)], []

    game_no = int(header.game_no or 0) + 1
    round_no = 1

    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(
        room_code,
        phase="DRAW",
        game_no=game_no,
        round_no=round_no,
        draw_end_at=ts + draw_window_sec,
        guess_end_at=0,
        team_guessed={"A": False, "B": False},
        team_guess_result={"A": "", "B": ""},
        winner_team="",
        winner_pid="",
        end_reason="",
        votes_next={},
        game_end_at=0,
        clear_ops_at=0,
    )

    await repo.set_budget_fields(room_code, A=stroke_limit, B=stroke_limit)
    await repo.update_room_fields(
        room_code,
        state="IN_GAME",
        round_no=round_no,
        game_no=game_no,
        last_activity=ts,
        countdown_end_at=0,
    )
    await repo.refresh_room_ttl(room_code, mode="VS")

    budget = await repo.get_budget(room_code)
    to_sender = [
        OutRoomStateChanged(state="IN_GAME"),
        OutPhaseChanged(phase="DRAW", round_no=round_no),
        OutBudgetUpdate(budget=budget),
        await _snapshot_for(app, room_code, viewer_pid=pid),
    ]
    to_room = [
        OutRoomStateChanged(state="IN_GAME"),
        OutPhaseChanged(phase="DRAW", round_no=round_no),
        OutBudgetUpdate(budget=budget),
    ]
    players = await repo.list_players(room_code)
    for p in players:
        if not getattr(p, "connected", True):
            continue
        snap = await _snapshot_for(app, room_code, viewer_pid=p.pid)
        to_room.append({**snap.model_dump(), "targets": [p.pid]})
    return to_sender, to_room
