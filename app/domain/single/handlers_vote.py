# app/domain/single/handlers_vote.py
from __future__ import annotations

from typing import List, Optional, Tuple

from app.domain.helpers.voting import record_vote_all_active
from app.transport.protocols import InVoteNext, OutError, OutRoomStateChanged
from app.util.timeutil import now_ts

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]


async def handle_single_vote_next(*, app, room_code: str, pid: Optional[str], msg: InVoteNext) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []
    if header.mode != "SINGLE":
        return [], []

    if header.state != "ROUND_END":
        return [OutError(code="BAD_STATE", message=f"Cannot vote_next in state {header.state}")], []

    game = await repo.get_game(room_code)
    if game.get("phase") != "VOTING":
        return [OutError(code="BAD_PHASE", message="vote_next only allowed in VOTING phase")], []

    votes, eligible = await record_vote_all_active(repo=repo, room_code=room_code, pid=pid, vote=msg.vote)
    if pid not in eligible:
        return [OutError(code="NOT_ACTIVE", message="Only active players can vote")], []

    if not eligible:
        return [OutError(code="NO_ELIGIBLE_VOTERS", message="No eligible voters")], []

    # Decide only after ALL eligible voters have voted
    if not all(p in votes for p in eligible):
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode=header.mode)
        return [], []

    yes_count = sum(1 for p in eligible if votes.get(p) == "yes")
    threshold = (len(eligible) // 2) + 1

    if yes_count >= threshold:
        # Clear roles and go back to ROLE_PICK (new roles will be assigned)
        players = await repo.list_players(room_code)
        for p in players:
            await repo.update_player_fields(room_code, p.pid, role=None)

        await repo.set_roles(room_code, {})
        await repo.clear_ops(room_code, mode="SINGLE")
        await repo.set_game_fields(room_code, phase="", votes_next={}, winner_pid="", end_reason="")
        await repo.update_room_fields(room_code, state="ROLE_PICK", gm_pid=None, last_activity=ts)
        await repo.vote_next_clear(room_code)
        await repo.refresh_room_ttl(room_code, mode=header.mode)

        from app.domain.lifecycle.handlers import _build_snapshot
        snap = await _build_snapshot(app, room_code, header.mode, viewer_pid=None, redact_secret=True)
        return [], [OutRoomStateChanged(state="ROLE_PICK"), snap]

    # No / tie -> stay ROUND_END, clear votes
    await repo.set_game_fields(room_code, phase="", votes_next={}, end_reason="VOTE_NO")
    await repo.vote_next_clear(room_code)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    from app.domain.lifecycle.handlers import _build_snapshot
    snap = await _build_snapshot(app, room_code, header.mode, viewer_pid=None, redact_secret=True)
    return [], [OutRoomStateChanged(state="ROUND_END"), snap]
