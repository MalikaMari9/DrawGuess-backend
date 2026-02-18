from typing import List, Optional, Tuple

from typing import List, Optional, Tuple

from app.domain.common.validation import is_gm
from app.transport.protocols import InEndGame, OutError, OutRoomStateChanged, OutPhaseChanged, OutGameEnd
from app.util.timeutil import now_ts

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]


async def handle_end_game(*, app, room_code: str, pid: Optional[str], msg: InEndGame) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []

    actor = await repo.get_player(room_code, pid)
    if not is_gm(actor, header):
        return [OutError(code="NOT_GM", message="Only GameMaster can end games")], []

    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(
        room_code,
        phase="VOTING",
        votes_next={},
        winner_team="",
        winner_pid="",
        end_reason="GM_END",
        vote_end_at=ts + 30 if header.mode == "VS" else 0,
        draw_end_at=0,
        guess_end_at=0,
        game_end_at=ts,
        clear_ops_at=ts + 5,
    )
    await repo.update_room_fields(room_code, state="GAME_END", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    round_cfg = await repo.get_round_config(room_code)
    word = round_cfg.get("secret_word", "")

    events = [
        OutRoomStateChanged(state="GAME_END"),
        OutPhaseChanged(phase="VOTING", round_no=header.round_no),
        OutGameEnd(winner=None, word=word, game_no=header.game_no, round_no=header.round_no, reason="GM_END"),
    ]
    return list(events), events
