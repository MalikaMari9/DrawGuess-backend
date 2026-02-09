# app/domain/vs/handlers_start_round.py
from __future__ import annotations

from typing import Optional

from .handlers_common import Result
from app.domain.vs.roles import auto_assign_vs_roles
from app.domain.vs.rules import validate_vs_start_conditions
from app.transport.protocols import (
    OutBudgetUpdate,
    OutError,
    OutPhaseChanged,
    OutRolesAssigned,
    OutRoomStateChanged,
    InStartRound,
)
from app.util.timeutil import now_ts


async def handle_vs_start_round(*, app, room_code: str, pid: Optional[str], msg: InStartRound) -> Result:
    """
    Start a VS mode round.
    GM provides:
    - secret_word       (hidden from non-GM clients)
    - time_limit_sec    (drawing phase duration)
    - strokes_per_phase (3-5 strokes per DRAW phase, per team)
    - guess_window_sec  (optional GUESS window duration)

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
        return [OutError(code="BAD_STATE", message=f"Cannot start round in state {header.state}")], []

    # Only GM can start round
    if header.gm_pid != pid:
        return [OutError(code="NOT_GM", message="Only GameMaster can start rounds")], []

    # Validate strokes_per_phase (3-5 as per spec)
    stroke_limit = msg.strokes_per_phase
    if stroke_limit < 3 or stroke_limit > 5:
        return [OutError(code="INVALID_STROKE_LIMIT", message="strokes_per_phase must be between 3 and 5")], []

    # Validate time_limit_sec (basic sanity)
    time_limit_sec = msg.time_limit_sec
    if time_limit_sec <= 0:
        return [OutError(code="INVALID_TIME_LIMIT", message="time_limit_sec must be > 0")], []

    # Validate guess_window_sec (basic sanity)
    guess_window_sec = msg.guess_window_sec
    if guess_window_sec <= 0:
        return [OutError(code="INVALID_GUESS_WINDOW", message="guess_window_sec must be > 0")], []

    players = await repo.list_players(room_code)
    teams = {
        "A": await repo.get_team_members(room_code, "A"),
        "B": await repo.get_team_members(room_code, "B"),
    }

    # Validate start conditions (exclude GM from validation)
    can_start, error = validate_vs_start_conditions(players, teams, gm_pid=header.gm_pid)
    if not can_start:
        return [OutError(code="START_FAILED", message=error)], []

    # Reset roles for the new round (auto-assign drawers/guessers)
    roles, error = await auto_assign_vs_roles(repo, room_code, header.gm_pid)
    if error:
        return [OutError(code="ROLE_ASSIGN_FAILED", message=error)], []

    # Initialize round
    round_no = header.round_no if header.round_no > 0 else 1

    # Clear any pending "next round" votes
    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(room_code, votes_next={})

    # Initialize score if missing
    current_game = await repo.get_game(room_code)
    if "score" not in current_game:
        await repo.set_game_fields(room_code, score={"A": 0, "B": 0})

    # Set round config with GM settings (kept server-side; secret_word is never broadcast)
    await repo.set_round_config(
        room_code,
        {
            "secret_word": msg.secret_word,
            "round_no": round_no,
            "round_started_at": ts,
            "round_end_at": ts + time_limit_sec,
            "time_limit_sec": time_limit_sec,
            "strokes_per_phase": stroke_limit,
            "guess_window_sec": guess_window_sec,
        },
    )

    # Initialize budgets with GM-configured strokes_per_phase
    await repo.set_budget_fields(room_code, A=stroke_limit, B=stroke_limit)

    # Initialize game state with DRAW phase and metadata
    await repo.set_game_fields(
        room_code,
        phase="DRAW",
        phase_no=1,
        round_no=round_no,
        round_started_at=ts,
        round_end_at=ts + time_limit_sec,
        guess_window_sec=guess_window_sec,
        guess_started_at=0,
        guess_end_at=0,
        winner_pid="",
        winner_team="",
        end_reason="",
    )

    # Clear previous ops
    await repo.clear_ops(room_code, "VS")

    await repo.update_room_fields(room_code, state="IN_ROUND", round_no=round_no, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    budget = await repo.get_budget(room_code)
    return [], [
        OutRolesAssigned(roles=roles),
        OutRoomStateChanged(state="IN_ROUND"),
        OutPhaseChanged(phase="DRAW", round_no=round_no),
        OutBudgetUpdate(budget=budget),
    ]
