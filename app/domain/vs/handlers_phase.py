# app/domain/vs/handlers_phase.py
from __future__ import annotations

from typing import Optional

from .handlers_common import Result, transition_guess_to_draw
from app.transport.protocols import OutBudgetUpdate, OutError, OutPhaseChanged, InPhaseTick, Phase
from app.util.timeutil import now_ts


async def handle_vs_phase_tick(*, app, room_code: str, pid: Optional[str], msg: InPhaseTick) -> Result:
    """
    Advance phase in VS mode.
    DRAW -> GUESS -> DRAW (repeat until correct guess or round ends).
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
        return [OutError(code="BAD_STATE", message=f"Cannot tick phase in state {header.state}")], []

    game = await repo.get_game(room_code)
    current_phase: Phase = game.get("phase", "DRAW")

    # Get GM-configured settings from round config
    round_cfg = await repo.get_round_config(room_code)
    stroke_limit = round_cfg.get("strokes_per_phase", 3)  # Default within 3-5
    guess_window_sec = round_cfg.get("guess_window_sec", 10)

    # Enforce round time limit
    round_end_at_raw = game.get("round_end_at", 0)
    try:
        round_end_at = int(round_end_at_raw) if round_end_at_raw else 0
    except (TypeError, ValueError):
        round_end_at = 0
    if round_end_at and ts >= round_end_at:
        return [OutError(code="ROUND_ENDED", message="Round time limit reached")], []

    if current_phase == "GUESS":
        guess_end_at_raw = game.get("guess_end_at", 0)
        try:
            guess_end_at = int(guess_end_at_raw) if guess_end_at_raw else 0
        except (TypeError, ValueError):
            guess_end_at = 0

        if guess_end_at and ts >= guess_end_at:
            return await transition_guess_to_draw(
                repo=repo,
                room_code=room_code,
                ts=ts,
                round_no=header.round_no,
                stroke_limit=stroke_limit,
            )

    # Only GM can advance phases (or auto-advance based on timer)
    if header.gm_pid != pid:
        return [OutError(code="NOT_GM", message="Only GameMaster can advance phases")], []

    if current_phase == "DRAW":
        # Transition to GUESS phase
        await repo.set_game_fields(
            room_code,
            phase="GUESS",
            phase_guesses={},
            guess_started_at=ts,
            guess_end_at=ts + int(guess_window_sec),
        )

        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")

        return [], [
            OutPhaseChanged(phase="GUESS", round_no=header.round_no),
        ]

    if current_phase == "GUESS":
        return await transition_guess_to_draw(
            repo=repo,
            room_code=room_code,
            ts=ts,
            round_no=header.round_no,
            stroke_limit=stroke_limit,
        )

    return [OutError(code="BAD_PHASE", message=f"Cannot tick from phase {current_phase}")], []
