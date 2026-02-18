from __future__ import annotations

from typing import List, Tuple

from app.transport.protocols import (
    OutgoingEvent,
    OutPhaseChanged,
    OutBudgetUpdate,
    OutRoomStateChanged,
    OutGameEnd,
    OutGuessResult,
)

Result = Tuple[List[OutgoingEvent], List[OutgoingEvent]]


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def enter_vs_draw_phase(
    *,
    repo,
    room_code: str,
    ts: int,
    round_no: int,
    draw_window_sec: int,
    stroke_limit: int,
) -> List[OutgoingEvent]:
    draw_window_sec = _int(draw_window_sec, 0)
    stroke_limit = _int(stroke_limit, 0)

    await repo.set_game_fields(
        room_code,
        phase="DRAW",
        round_no=round_no,
        draw_end_at=ts + draw_window_sec,
        guess_end_at=0,
        team_guessed={"A": False, "B": False},
        team_guess_result={"A": "", "B": ""},
        winner_team="",
        winner_pid="",
        end_reason="",
    )
    await repo.set_budget_fields(room_code, A=stroke_limit, B=stroke_limit)
    await repo.update_room_fields(room_code, last_activity=ts, round_no=round_no)
    await repo.refresh_room_ttl(room_code, mode="VS")

    budget = await repo.get_budget(room_code)
    return [
        OutPhaseChanged(phase="DRAW", round_no=round_no),
        OutBudgetUpdate(budget=budget),
    ]


async def enter_vs_guess_phase(
    *,
    repo,
    room_code: str,
    ts: int,
    round_no: int,
    guess_window_sec: int,
) -> List[OutgoingEvent]:
    guess_window_sec = _int(guess_window_sec, 0)

    await repo.set_game_fields(
        room_code,
        phase="GUESS",
        guess_end_at=ts + guess_window_sec,
        draw_end_at=0,
    )
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    return [OutPhaseChanged(phase="GUESS", round_no=round_no)]


async def end_vs_game(
    *,
    repo,
    room_code: str,
    header,
    ts: int,
    winner_team: str | None,
    winner_pid: str,
    word: str,
    reason: str,
) -> List[OutgoingEvent]:
    # Keep roles/teams through GAME_END so the end screen can show a leaderboard.
    # Identity is stripped only after vote-YES resolves.
    if winner_team in ("A", "B"):
        players = await repo.list_players(room_code)
        for p in players:
            if not getattr(p, "connected", True):
                continue

            effective_team = getattr(p, "team", None)
            if effective_team is None:
                role = (getattr(p, "role", None) or "").strip()
                if role.endswith("A"):
                    effective_team = "A"
                elif role.endswith("B"):
                    effective_team = "B"

            if effective_team != winner_team:
                continue

            pts = int(getattr(p, "points", 0) or 0)
            await repo.update_player_fields(room_code, p.pid, points=pts + 1)

    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(
        room_code,
        phase="VOTING",
        winner_team=winner_team or "",
        winner_pid=winner_pid or "",
        end_reason=reason,
        votes_next={},
        vote_end_at=ts + 30,
        draw_end_at=0,
        guess_end_at=0,
        game_end_at=ts,
        clear_ops_at=ts + 5,
    )
    await repo.update_room_fields(room_code, state="GAME_END", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    return [
        OutRoomStateChanged(state="GAME_END"),
        OutPhaseChanged(phase="VOTING", round_no=header.round_no),
        OutGameEnd(
            winner=winner_team or None,
            word=word,
            game_no=header.game_no,
            round_no=header.round_no,
            reason=reason,
        ),
    ]


async def advance_vs_round_or_end_game(
    *,
    repo,
    room_code: str,
    header,
    ts: int,
    round_cfg: dict,
) -> List[OutgoingEvent]:
    max_rounds = _int(round_cfg.get("max_rounds"), 1)
    if header.round_no >= max_rounds:
        word = round_cfg.get("secret_word", "")
        return await end_vs_game(
            repo=repo,
            room_code=room_code,
            header=header,
            ts=ts,
            winner_team=None,
            winner_pid="",
            word=word,
            reason="NO_WINNER",
        )

    new_round_no = header.round_no + 1
    draw_window_sec = _int(round_cfg.get("draw_window_sec"), 60)
    stroke_limit = _int(round_cfg.get("strokes_per_phase"), 3)

    return await enter_vs_draw_phase(
        repo=repo,
        room_code=room_code,
        ts=ts,
        round_no=new_round_no,
        draw_window_sec=draw_window_sec,
        stroke_limit=stroke_limit,
    )


async def auto_advance_vs_phase(*, repo, room_code: str, header, ts: int) -> List[OutgoingEvent]:
    if header.mode != "VS":
        return []
    if header.state != "IN_GAME":
        return []

    game = await repo.get_game(room_code)
    phase = game.get("phase") or "DRAW"
    round_cfg = await repo.get_round_config(room_code)

    if phase == "DRAW":
        draw_end_at = _int(game.get("draw_end_at"), 0)
        if draw_end_at and ts >= draw_end_at:
            guess_window_sec = _int(round_cfg.get("guess_window_sec"), 10)
            return await enter_vs_guess_phase(
                repo=repo,
                room_code=room_code,
                ts=ts,
                round_no=header.round_no,
                guess_window_sec=guess_window_sec,
            )

    if phase == "GUESS":
        guess_end_at = _int(game.get("guess_end_at"), 0)
        if guess_end_at and ts >= guess_end_at:
            team_guessed = game.get("team_guessed") or {}
            team_guess_result = game.get("team_guess_result") or {}
            events: List[OutgoingEvent] = []

            for team in ("A", "B"):
                if not team_guessed.get(team):
                    team_guessed[team] = True
                    team_guess_result[team] = "NO_GUESS"
                    events.append(
                        OutGuessResult(
                            result="NO_GUESS",
                            team=team,
                            text="",
                            by="",
                            correct=False,
                        )
                    )

            await repo.set_game_fields(
                room_code,
                team_guessed=team_guessed,
                team_guess_result=team_guess_result,
            )

            advance_events = await advance_vs_round_or_end_game(
                repo=repo,
                room_code=room_code,
                header=header,
                ts=ts,
                round_cfg=round_cfg,
            )
            return [*events, *advance_events]

    return []
