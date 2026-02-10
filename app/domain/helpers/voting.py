from __future__ import annotations

from typing import Dict, List, Tuple


async def record_vote_all_active(
    *,
    repo,
    room_code: str,
    pid: str,
    vote: str,
) -> Tuple[Dict[str, str], List[str]]:
    """
    Record a vote from an active player.
    - Eligible voters: all active players (GM included).
    - Drops votes from inactive players.
    - Rebuilds the yes-vote set to match current eligible votes.
    Returns (votes, eligible_pids).
    """
    active_pids = await repo.get_active_pids(room_code)
    eligible = list(active_pids)

    if pid not in active_pids:
        return {}, eligible

    game = await repo.get_game(room_code)
    votes = game.get("votes_next") or {}
    if not isinstance(votes, dict):
        votes = {}

    # Drop votes from inactive players and update current vote
    votes = {p: v for p, v in votes.items() if p in active_pids}
    votes[pid] = vote

    await repo.set_game_fields(room_code, votes_next=votes)

    # Rebuild yes-vote set
    await repo.vote_next_clear(room_code)
    for p, v in votes.items():
        if v == "yes":
            await repo.vote_next_add(room_code, p)

    return votes, eligible
