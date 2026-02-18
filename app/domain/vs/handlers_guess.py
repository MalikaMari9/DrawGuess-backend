from __future__ import annotations

from typing import Optional

from app.domain.common.validation import is_guesser, is_muted
from .handlers_common import Result, auto_advance_vs_phase, enter_vs_transition
from app.transport.protocols import OutError, OutGuessResult, InGuess
from app.util.timeutil import now_ts


def _norm(s: str) -> str:
    return "".join((s or "").strip().lower().split())


async def handle_vs_guess(*, app, room_code: str, pid: Optional[str], msg: InGuess) -> Result:
    """
    Handle guesses in VS mode.
    One guess per team per round (any guesser can take it).
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
        events = await auto_advance_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)
        return [OutError(code="GUESS_EXPIRED", message="Guess window ended")], events

    player = await repo.get_player(room_code, pid)
    if player is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found")], []

    if is_muted(player, ts):
        return [OutError(code="MUTED", message="You are muted")], []

    if not is_guesser(player):
        return [OutError(code="NOT_GUESSER", message="Only guessers can guess")], []

    if player.team is None:
        return [OutError(code="NO_TEAM", message="Player has no team")], []

    guess_text = (msg.text or "").strip()
    if not guess_text:
        return [OutError(code="EMPTY_GUESS", message="Empty guess")], []

    team_guessed = game.get("team_guessed") or {}
    team_guess_result = game.get("team_guess_result") or {}

    if team_guessed.get(player.team):
        return [OutError(code="TEAM_ALREADY_GUESSED", message="Team already guessed this round")], []

    round_cfg = await repo.get_round_config(room_code)
    word_raw = round_cfg.get("secret_word", "")
    word = _norm(word_raw)
    correct = _norm(guess_text) == word
    result = "CORRECT" if correct else "WRONG"

    team_guessed[player.team] = True
    team_guess_result[player.team] = result
    await repo.set_game_fields(
        room_code,
        team_guessed=team_guessed,
        team_guess_result=team_guess_result,
    )

    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    guess_event = OutGuessResult(
        result=result,
        team=player.team,
        text=guess_text,
        by=pid,
        correct=correct,
    )

    to_room = [guess_event]

    if correct:
        transition_events = await enter_vs_transition(
            repo=repo,
            room_code=room_code,
            ts=ts,
            round_no=header.round_no,
            front="WE FOUND A WINNER!!",
            back=f"Correct guess is {word_raw}",
            next_phase="GAME_END",
            winner_team=player.team,
            winner_pid=pid,
            word=word_raw,
            reason="CORRECT",
        )
        to_room.extend(transition_events)
        return list(to_room), to_room

    if team_guessed.get("A") and team_guessed.get("B"):
        max_rounds = int(round_cfg.get("max_rounds") or 1)
        if header.round_no >= max_rounds:
            transition_events = await enter_vs_transition(
                repo=repo,
                room_code=room_code,
                ts=ts,
                round_no=header.round_no,
                front="NO ONE GUESSED CORRECTLY",
                back="NO WINNER",
                next_phase="GAME_END",
                winner_team=None,
                winner_pid="",
                word=word_raw,
                reason="NO_WINNER",
            )
        else:
            transition_events = await enter_vs_transition(
                repo=repo,
                room_code=room_code,
                ts=ts,
                round_no=header.round_no,
                front="NO ONE GUESSED CORRECTLY",
                back="DRAW PHASE",
                next_phase="DRAW",
                next_round_no=header.round_no + 1,
            )
        to_room.extend(transition_events)
        return list(to_room), to_room

    return list(to_room), to_room
