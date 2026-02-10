from __future__ import annotations

import random
from typing import Iterable, List, Tuple

from app.store.models import PlayerStore


def _pick_random(players: List[PlayerStore], seed: str) -> PlayerStore:
    rng = random.Random(seed)
    return rng.choice(players)


async def assign_single_roles(
    *,
    repo,
    room_code: str,
    connected: Iterable[PlayerStore],
    gm_pid: str | None,
    seed: str,
) -> Tuple[str, str, List[str]]:
    """
    Assign SINGLE roles:
      - GM (if not already assigned)
      - Drawer (random, excluding GM if possible)
      - Guessers (all remaining connected players)

    Persists gm_pid to room header, roles hash (gm/drawer), and player.role fields.
    Returns (gm_pid, drawer_pid, guesser_pids).
    """
    connected_list = [p for p in connected if getattr(p, "connected", False)]
    if not connected_list:
        return "", "", []

    # Assign GM if missing
    if not gm_pid:
        gm = _pick_random(connected_list, seed)
        gm_pid = gm.pid
        await repo.update_room_fields(room_code, gm_pid=gm_pid)

    # Drawer (prefer non-GM)
    non_gm = [p for p in connected_list if p.pid != gm_pid]
    if non_gm:
        drawer = _pick_random(non_gm, seed + ":drawer")
    else:
        drawer = _pick_random(connected_list, seed + ":drawer")
    drawer_pid = drawer.pid

    guesser_pids = [p.pid for p in connected_list if p.pid not in (gm_pid, drawer_pid)]

    # Persist roles hash (gm/drawer only)
    await repo.set_roles(room_code, {"gm": gm_pid, "drawer": drawer_pid})

    # Persist per-player role (gm/drawer/guesser)
    for p in connected_list:
        if p.pid == gm_pid:
            await repo.update_player_fields(room_code, p.pid, role="gm")
        elif p.pid == drawer_pid:
            await repo.update_player_fields(room_code, p.pid, role="drawer")
        else:
            await repo.update_player_fields(room_code, p.pid, role="guesser")

    return gm_pid, drawer_pid, guesser_pids
