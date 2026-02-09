# app/domain/vs/handlers_guess.py
from __future__ import annotations

from typing import Optional

from app.domain.common.validation import is_guesser, is_muted
from .handlers_common import Result, transition_guess_to_voting
from app.transport.protocols import OutError, OutGuessResult, OutRoomStateChanged, OutRoundEnd, InGuess
from app.util.timeutil import now_ts


async def handle_vs_guess(*, app, room_code: str, pid: Optional[str], msg: InGuess) -> Result:
    """
    Handle guesses in VS mode.
    Each team gets one guess per phase.
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
        return [OutError(code="BAD_STATE", message=f"Cannot guess in state {header.state}")], []

    game = await repo.get_game(room_code)
    if game.get("phase") != "GUESS":
        return [OutError(code="BAD_PHASE", message="Not in GUESS phase")], []

    guess_end_at_raw = game.get("guess_end_at", 0)
    try:
        guess_end_at = int(guess_end_at_raw) if guess_end_at_raw else 0
    except (TypeError, ValueError):
        guess_end_at = 0

    if guess_end_at and ts >= guess_end_at:
        _, to_room = await transition_guess_to_voting(
            repo=repo,
            room_code=room_code,
            ts=ts,
            round_no=header.round_no,
        )
        return [OutError(code="GUESS_EXPIRED", message="Guess phase timer expired")], to_room

    player = await repo.get_player(room_code, pid)
    if player is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found")], []

    if is_muted(player, ts):
        return [OutError(code="MUTED", message="You are muted")], []

    if not is_guesser(player):
        return [OutError(code="NOT_GUESSER", message="Only guessers can guess")], []

    if player.team is None:
        return [OutError(code="NO_TEAM", message="Player has no team")], []

    # Check if team already guessed this phase
    phase_guesses = game.get("phase_guesses", {})
    if player.team in phase_guesses:
        return [OutError(code="ALREADY_GUESSED", message="Your team already guessed this phase")], []

    # Get word
    round_cfg = await repo.get_round_config(room_code)
    word_raw = round_cfg.get("secret_word", "")
    word = word_raw.lower().strip()
    guess_text = msg.text.lower().strip()

    # Check if correct
    correct = guess_text == word

    # Record guess
    phase_guesses[player.team] = {
        "text": msg.text,
        "by": pid,
        "ts": ts,
        "correct": correct,
    }
    await repo.set_game_fields(room_code, phase_guesses=phase_guesses)

    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    # If correct, end round
    if correct:
        # Update score and move to VOTING phase
        game = await repo.get_game(room_code)
        score = game.get("score") or {"A": 0, "B": 0}
        if player.team in ["A", "B"]:
            score[player.team] = int(score.get(player.team, 0)) + 1
        await repo.set_game_fields(room_code, score=score, phase="VOTING")

        # Persist round end metadata
        await repo.set_game_fields(
            room_code,
            winner_team=player.team or "",
            winner_pid=pid,
            end_reason="CORRECT",
            round_end_at=ts,
        )
        await repo.set_game_fields(
            room_code,
            phase="",
            phase_guesses={},
            votes_next={},
            guess_started_at=0,
            guess_end_at=0,
        )
        await repo.update_room_fields(room_code, state="ROUND_END", last_activity=ts)
        await repo.vote_next_clear(room_code)
        return [], [
            OutGuessResult(correct=True, team=player.team, text=msg.text, by=pid),
            OutRoundEnd(winner=player.team, word=word_raw, round_no=header.round_no),
            OutRoomStateChanged(state="ROUND_END"),
        ]

    # Otherwise, broadcast guess result
    return [], [OutGuessResult(correct=False, team=player.team, text=msg.text, by=pid)]
