# app/domain/vs/handlers_vote.py
from __future__ import annotations

import random
from typing import Optional

from .handlers_common import Result
from app.domain.helpers.voting import record_vote_all_active
from app.transport.protocols import OutError, OutRoomStateChanged, OutRoundEnd, InVoteNext
from app.util.timeutil import now_ts


async def handle_vs_vote_next(*, app, room_code: str, pid: Optional[str], msg: InVoteNext) -> Result:
    """
    Vote to end the current round and proceed to next round.
    Non-GM team members only. Majority of active non-GM players required.
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

    if header.state not in ["IN_ROUND", "ROUND_END"]:
        return [OutError(code="BAD_STATE", message=f"Cannot vote in state {header.state}")], []

    player = await repo.get_player(room_code, pid)
    if player is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found")], []

    if player.team is None:
        return [OutError(code="NO_TEAM", message="Player has no team")], []

    game = await repo.get_game(room_code)
    if game.get("phase") != "VOTING":
        return [OutError(code="BAD_PHASE", message="Vote next is only allowed in VOTING phase")], []

    votes, eligible = await record_vote_all_active(repo=repo, room_code=room_code, pid=pid, vote=msg.vote)
    if pid not in eligible:
        return [OutError(code="NOT_ACTIVE", message="Only active players can vote")], []
    if not eligible:
        return [OutError(code="NO_ELIGIBLE_VOTERS", message="No eligible voters")], []

    # Decide only after ALL eligible voters have voted
    if not all(p in votes for p in eligible):
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")
        return [], []

    yes_count = sum(1 for p in eligible if votes.get(p) == "yes")
    no_count = sum(1 for p in eligible if votes.get(p) == "no")
    threshold = (len(eligible) // 2) + 1

    if yes_count >= threshold:
        # Yes wins -> rotate GM, clear roles, move to ROLE_PICK
        players = await repo.list_players(room_code)
        connected = [p for p in players if p.connected]
        if not connected:
            return [OutError(code="NO_PLAYERS", message="No connected players to assign GM")], []

        candidates = [p for p in connected if p.pid != header.gm_pid] or connected
        new_gm_pid = random.choice(candidates).pid

        # Clear roles so UI doesn't show stale roles between rounds
        await repo.set_roles(room_code, {})
        for p in players:
            await repo.update_player_fields(room_code, p.pid, role=None)
        await repo.clear_team(room_code, new_gm_pid)

        await repo.set_game_fields(
            room_code,
            phase="",
            phase_guesses={},
            votes_next={},
            guess_started_at=0,
            guess_end_at=0,
        )
        await repo.update_room_fields(
            room_code,
            state="ROLE_PICK",
            gm_pid=new_gm_pid,
            round_no=header.round_no + 1,
            last_activity=ts,
        )
        await repo.vote_next_clear(room_code)
        await repo.refresh_room_ttl(room_code, mode="VS")

        return [], [
            OutRoomStateChanged(state="ROLE_PICK"),
        ]

    # No wins (or tie) -> end round, remain ROUND_END
    round_cfg = await repo.get_round_config(room_code)
    await repo.set_game_fields(
        room_code,
        phase="",
        phase_guesses={},
        votes_next={},
        guess_started_at=0,
        guess_end_at=0,
        winner_team="",
        winner_pid="",
        end_reason="VOTE_NO",
        round_end_at=ts,
    )
    await repo.update_room_fields(room_code, state="ROUND_END", last_activity=ts)
    await repo.vote_next_clear(room_code)
    await repo.refresh_room_ttl(room_code, mode="VS")

    return [], [
        OutRoundEnd(winner=None, word=round_cfg.get("secret_word", ""), round_no=header.round_no),
        OutRoomStateChanged(state="ROUND_END"),
    ]
