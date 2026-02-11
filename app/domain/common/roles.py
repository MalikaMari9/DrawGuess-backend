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
