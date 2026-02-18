from __future__ import annotations

from typing import Optional

from .handlers_common import Result
from app.domain.helpers.voting import record_vote_all_active
from app.domain.common.roles import strip_identity
from app.transport.protocols import OutError, OutVoteResolved, OutVoteProgress, InVoteNext
from app.util.timeutil import now_ts


async def handle_vs_vote_next(*, app, room_code: str, pid: Optional[str], msg: InVoteNext) -> Result:
    """
    Vote to start the next game after GAME_END.
    Everyone can vote (GM included). Majority of active players required.
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

    if header.state != "GAME_END":
        return [OutError(code="BAD_STATE", message=f"Cannot vote in state {header.state}")], []

    player = await repo.get_player(room_code, pid)
    if player is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found")], []

    game = await repo.get_game(room_code)
    if game.get("phase") != "VOTING":
        return [OutError(code="BAD_PHASE", message="vote_next only allowed in VOTING phase")], []

    vote_end_at_raw = game.get("vote_end_at", 0)
    try:
        vote_end_at = int(vote_end_at_raw) if vote_end_at_raw else 0
    except (TypeError, ValueError):
        vote_end_at = 0
    if vote_end_at and ts >= vote_end_at:
        return [OutError(code="VOTE_EXPIRED", message="Vote window ended")], []

    votes, eligible = await record_vote_all_active(repo=repo, room_code=room_code, pid=pid, vote=msg.vote)

    if pid not in eligible:
        return [OutError(code="NOT_ACTIVE", message="Only active players can vote")], []
    if not eligible:
        return [OutError(code="NO_ELIGIBLE_VOTERS", message="No eligible voters")], []

    yes_count = sum(1 for p in eligible if votes.get(p) == "yes")
    threshold = (len(eligible) // 2) + 1
    voted_count = sum(1 for p in eligible if p in votes)

    vote_end_at_raw = game.get("vote_end_at", 0)
    try:
        vote_end_at = int(vote_end_at_raw) if vote_end_at_raw else 0
    except (TypeError, ValueError):
        vote_end_at = 0

    progress = OutVoteProgress(
        ts=ts,
        vote_end_at=vote_end_at,
        yes_count=yes_count,
        voted_count=voted_count,
        eligible=len(eligible),
    )

    if yes_count >= threshold:
        # Keep GAME_END visible briefly, then lifecycle handler resets identity and returns to lobby.
        await repo.set_game_fields(room_code, reset_to_waiting_at=ts + 2, vote_end_at=0, vote_outcome="YES")
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")
        ev = OutVoteResolved(outcome="YES", ts=ts, yes_count=yes_count, eligible=len(eligible))
        return [progress, ev], [progress, ev]

    # If everyone voted and we still don't have majority YES, resolve to FINAL leaderboard.
    if all(p in votes for p in eligible):
        # Strip identity so FINAL shows points only (no GM/team/role).
        await strip_identity(repo, room_code)
        await repo.set_game_fields(room_code, phase="FINAL", vote_end_at=0, vote_outcome="NO")
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")
        ev = OutVoteResolved(outcome="NO", ts=ts, yes_count=yes_count, eligible=len(eligible))
        return [progress, ev], [progress, ev]

    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")
    return [progress], [progress]

    # No explicit NO-resolution here; vote timeout handles "missing counts as NO".
