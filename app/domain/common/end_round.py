from __future__ import annotations

from typing import List, Optional, Tuple

from app.domain.common.roles import clear_all_roles
from app.domain.common.validation import is_gm
from app.transport.protocols import InEndRound, OutError, OutRoomStateChanged, OutPhaseChanged, OutRoundEnd
from app.util.timeutil import now_ts

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]


async def handle_end_round(*, app, room_code: str, pid: Optional[str], msg: InEndRound) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []

    actor = await repo.get_player(room_code, pid)
    if not is_gm(actor, header):
        return [OutError(code="NOT_GM", message="Only GameMaster can end rounds")], []

    # Clear roles for everyone when entering VOTING
    await clear_all_roles(repo, room_code)

    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(
        room_code,
        phase="VOTING",
        phase_guesses={},
        votes_next={},
        winner_team="",
        winner_pid="",
        end_reason="GM_END",
        round_end_at=ts,
    )
    await repo.update_room_fields(room_code, state="ROUND_END", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    round_cfg = await repo.get_round_config(room_code)
    word = round_cfg.get("secret_word", "")

    events = [
        OutRoomStateChanged(state="ROUND_END"),
        OutPhaseChanged(phase="VOTING", round_no=header.round_no),
        OutRoundEnd(winner=None, word=word, round_no=header.round_no),
    ]
    return [], events
