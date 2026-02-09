# app/domain/vs/handlers_common.py
from __future__ import annotations

from typing import List, Tuple

from app.transport.protocols import OutgoingEvent, OutPhaseChanged

Result = Tuple[List[OutgoingEvent], List[OutgoingEvent]]


async def transition_guess_to_voting(*, repo, room_code: str, ts: int, round_no: int) -> Result:
    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(
        room_code,
        phase="VOTING",
        phase_guesses={},
        votes_next={},
        guess_started_at=0,
        guess_end_at=0,
    )

    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    return [], [OutPhaseChanged(phase="VOTING", round_no=round_no)]
