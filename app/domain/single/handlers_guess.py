from __future__ import annotations

from typing import List, Optional, Tuple

from app.transport.protocols import (
    InGuess,
    OutError,
    OutGuessChat,
    OutGuessResult,
    OutPhaseChanged,
)
from app.util.timeutil import now_ts
from app.domain.lifecycle.handlers import _auto_expire_single_game

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]
SINGLE_TRANSITION_SEC = 5


def _norm(s: str) -> str:
    return "".join((s or "").strip().lower().split())


async def handle_single_guess(*, app, room_code: str, pid: Optional[str], msg: InGuess) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []
    if header.mode != "SINGLE":
        return [OutError(code="NOT_SINGLE", message="This handler is for SINGLE mode only")], []
    if header.state != "IN_GAME":
        return [OutError(code="NOT_IN_GAME", message="Game not started")], []

    tick_events = await _auto_expire_single_game(repo=repo, room_code=room_code, header=header, ts=ts)
    if tick_events:
        return list(tick_events), tick_events

    game = await repo.get_game(room_code)
    phase = str(game.get("phase") or "").upper()
    # Keep GUESS accepted as a temporary compatibility path for in-flight legacy rooms.
    if phase not in ("DRAW", "GUESS"):
        return [OutError(code="BAD_PHASE", message="Not in active round")], []

    player = await repo.get_player(room_code, pid)
    if player is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found")], []
    if getattr(player, "role", None) != "guesser":
        return [OutError(code="NOT_GUESSER", message="Only guessers can guess")], []

    text_guess = (msg.text or "").strip()
    if not text_guess:
        return [OutError(code="EMPTY_GUESS", message="Empty guess")], []

    round_cfg = await repo.get_round_config(room_code)
    secret = (round_cfg.get("secret_word") or "").strip()
    if not secret:
        return [OutError(code="NO_WORD_SET", message="No word set")], []

    chat_ev = OutGuessChat(ts=ts, pid=pid, name=player.name, text=text_guess)

    correct = _norm(text_guess) == _norm(secret)
    result_ev = OutGuessResult(
        result="CORRECT" if correct else "WRONG",
        team=None,
        text=text_guess,
        by=pid,
        correct=correct,
    )

    to_sender: List[object] = [chat_ev, result_ev]
    to_room: List[object] = [chat_ev, result_ev]

    if correct:
        await repo.set_game_fields(
            room_code,
            phase="TRANSITION",
            transition_until=ts + SINGLE_TRANSITION_SEC,
            transition_front="WE FOUND A WINNER!!",
            transition_back=f"Correct guess is {secret}",
            transition_next="GAME_END",
            transition_reason="CORRECT",
            transition_word=secret,
            transition_winner_pid=pid,
            transition_round_no=header.round_no,
            draw_end_at=0,
            guess_end_at=0,
        )
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode=header.mode)

        to_room.extend(
            [
                OutPhaseChanged(phase="TRANSITION", round_no=header.round_no),
            ]
        )
        to_sender.extend(
            [
                OutPhaseChanged(phase="TRANSITION", round_no=header.round_no),
            ]
        )

    return to_sender, to_room
