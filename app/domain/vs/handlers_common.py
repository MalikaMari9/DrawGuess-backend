# app/domain/vs/handlers_common.py
from __future__ import annotations

from typing import List, Tuple

from app.transport.protocols import OutgoingEvent, OutPhaseChanged, OutBudgetUpdate, OutRoomStateChanged, OutRoundEnd

Result = Tuple[List[OutgoingEvent], List[OutgoingEvent]]


async def transition_guess_to_draw(
    *,
    repo,
    room_code: str,
    ts: int,
    round_no: int,
    stroke_limit: int,
) -> Result:
    await repo.set_game_fields(
        room_code,
        phase="DRAW",
        phase_guesses={},
        guess_started_at=0,
        guess_end_at=0,
    )
    await repo.set_budget_fields(room_code, A=stroke_limit, B=stroke_limit)

    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    budget = await repo.get_budget(room_code)
    return [], [
        OutPhaseChanged(phase="DRAW", round_no=round_no),
        OutBudgetUpdate(budget=budget),
    ]


async def transition_draw_to_guess(
    *,
    repo,
    room_code: str,
    ts: int,
    round_no: int,
    guess_window_sec: int,
) -> Result:
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
        OutPhaseChanged(phase="GUESS", round_no=round_no),
    ]


async def transition_guess_to_voting_no_winner(
    *,
    repo,
    room_code: str,
    ts: int,
    round_no: int,
    word: str,
) -> Result:
    from app.domain.common.roles import clear_all_roles
    await clear_all_roles(repo, room_code)
    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(
        room_code,
        phase="VOTING",
        phase_guesses={},
        votes_next={},
        guess_started_at=0,
        guess_end_at=0,
        winner_team="",
        winner_pid="",
        end_reason="NO_CORRECT",
        round_end_at=ts,
    )
    await repo.update_room_fields(room_code, state="ROUND_END", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    return [], [
        OutRoomStateChanged(state="ROUND_END"),
        OutPhaseChanged(phase="VOTING", round_no=round_no),
        OutRoundEnd(winner=None, word=word, round_no=round_no),
    ]
