# app/domain/vs/handlers_common.py
from __future__ import annotations

from typing import List, Tuple

from app.transport.protocols import OutgoingEvent, OutPhaseChanged, OutBudgetUpdate

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
