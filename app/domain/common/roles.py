from __future__ import annotations

from typing import Any


async def clear_all_roles(repo: Any, room_code: str) -> None:
    """
    Clear roles hash and per-player role fields for the room.
    """
    await repo.set_roles(room_code, {})
    players = await repo.list_players(room_code)
    for p in players:
        await repo.update_player_fields(room_code, p.pid, role=None)


async def strip_identity(repo: Any, room_code: str) -> None:
    """
    Strip all per-game identity from the room (roles/teams/GM), but keep player points.
    Used after a VS vote resolves to NO (FINAL leaderboard should show points only).
    """
    await clear_all_roles(repo, room_code)

    players = await repo.list_players(room_code)
    for p in players:
        await repo.clear_team(room_code, p.pid)

    await repo.clear_room_field(room_code, "gm_pid")
