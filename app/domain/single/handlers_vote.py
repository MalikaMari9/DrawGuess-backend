from __future__ import annotations

import asyncio
import logging
from typing import List, Optional, Tuple

from app.domain.helpers.voting import record_vote_all_active
from app.transport.protocols import InVoteNext, OutError, OutVoteProgress, OutVoteResolved
from app.util.timeutil import now_ts

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]

_ROOM_VOTE_LOCKS: dict[str, asyncio.Lock] = {}
logger = logging.getLogger(__name__)


async def handle_single_vote_next(*, app, room_code: str, pid: Optional[str], msg: InVoteNext) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    lock = _ROOM_VOTE_LOCKS.setdefault(room_code, asyncio.Lock())
    async with lock:
        repo = app.state.repo
        ts = now_ts()

        header = await repo.get_room_header(room_code)
        if header is None:
            return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []
        if header.mode != "SINGLE":
            return [OutError(code="NOT_SINGLE", message="This handler is for SINGLE mode only")], []

        if header.state != "GAME_END":
            return [OutError(code="BAD_STATE", message=f"Cannot vote_next in state {header.state}")], []

        game = await repo.get_game(room_code)
        if game.get("phase") != "VOTING":
            return [OutError(code="BAD_PHASE", message="vote_next only allowed in VOTING phase")], []

        logger.info(
            "[FLOW][BE][single_vote_next] room=%s pid=%s vote=%s state=%s phase=%s ts=%s",
            room_code,
            pid,
            getattr(msg, "vote", None),
            getattr(header, "state", None),
            game.get("phase"),
            ts,
        )

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

        game = await repo.get_game(room_code)
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
            # Keep GAME_END briefly; heartbeat lifecycle resets to WAITING like VS.
            await repo.set_game_fields(
                room_code,
                reset_to_waiting_at=ts + 2,
                vote_end_at=0,
                vote_outcome="YES",
            )
            await repo.update_room_fields(room_code, last_activity=ts)
            await repo.refresh_room_ttl(room_code, mode=header.mode)
            logger.info(
                "[FLOW][BE][single_vote_next] room=%s outcome=YES yes=%s voted=%s eligible=%s reset_to_waiting_at=%s",
                room_code,
                yes_count,
                voted_count,
                len(eligible),
                ts + 2,
            )
            ev = OutVoteResolved(outcome="YES", ts=ts, yes_count=yes_count, eligible=len(eligible))
            return [progress, ev], [progress, ev]

        # No majority yet and vote is still in progress.
        if voted_count < len(eligible):
            await repo.update_room_fields(room_code, last_activity=ts)
            await repo.refresh_room_ttl(room_code, mode=header.mode)
            logger.info(
                "[FLOW][BE][single_vote_next] room=%s outcome=PENDING yes=%s voted=%s eligible=%s",
                room_code,
                yes_count,
                voted_count,
                len(eligible),
            )
            return [progress], [progress]

        # Everyone voted with no YES-majority -> final leaderboard in GAME_END.
        await repo.set_game_fields(
            room_code,
            phase="FINAL",
            vote_end_at=0,
            vote_outcome="NO",
            end_reason="VOTE_NO",
        )
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode=header.mode)
        logger.info(
            "[FLOW][BE][single_vote_next] room=%s outcome=NO yes=%s voted=%s eligible=%s",
            room_code,
            yes_count,
            voted_count,
            len(eligible),
        )
        ev = OutVoteResolved(outcome="NO", ts=ts, yes_count=yes_count, eligible=len(eligible))
        return [progress, ev], [progress, ev]
