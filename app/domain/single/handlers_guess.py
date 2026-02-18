from __future__ import annotations

from typing import List, Optional, Tuple

from app.transport.protocols import (
    InGuess,
    OutError,
    OutGuessChat,
    OutGuessResult,
    OutRoomStateChanged,
    OutPhaseChanged,
    OutGameEnd,
)
from app.util.timeutil import now_ts
from app.domain.lifecycle.handlers import _auto_expire_single_game

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]


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

    timeout_events = await _auto_expire_single_game(repo=repo, room_code=room_code, header=header, ts=ts)
    if timeout_events:
        return [OutError(code="GAME_ENDED", message="Game timed out")], timeout_events

    game = await repo.get_game(room_code)
    if game.get("phase") not in ("GUESS", "DRAW"):
        return [OutError(code="BAD_PHASE", message="Not in DRAW or GUESS phase")], []

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
        drawer_pid = str(game.get("drawer_pid") or "")
        guesser_points = int(getattr(player, "points", 0) or 0)
        await repo.update_player_fields(room_code, pid, points=guesser_points + 1)
        if drawer_pid:
            drawer = await repo.get_player(room_code, drawer_pid)
            if drawer is not None:
                drawer_points = int(getattr(drawer, "points", 0) or 0)
                await repo.update_player_fields(room_code, drawer_pid, points=drawer_points + 1)

        from app.domain.common.roles import clear_all_roles
        await clear_all_roles(repo, room_code)
        await repo.vote_next_clear(room_code)
        await repo.set_game_fields(
            room_code,
            phase="VOTING",
            winner_pid=pid,
            end_reason="CORRECT",
            game_end_at=ts,
            votes_next={},
            clear_ops_at=ts + 5,
        )
        await repo.update_room_fields(room_code, state="GAME_END", last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode=header.mode)

        to_room.extend(
            [
                OutRoomStateChanged(state="GAME_END"),
                OutPhaseChanged(phase="VOTING", round_no=header.round_no),
                OutGameEnd(winner=None, word=secret, game_no=header.game_no, round_no=header.round_no, reason="CORRECT"),
            ]
        )
        to_sender.extend(
            [
                OutRoomStateChanged(state="GAME_END"),
                OutPhaseChanged(phase="VOTING", round_no=header.round_no),
                OutGameEnd(winner=None, word=secret, game_no=header.game_no, round_no=header.round_no, reason="CORRECT"),
            ]
        )

    return to_sender, to_room
