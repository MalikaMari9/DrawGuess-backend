from __future__ import annotations

import random
from typing import Optional, Tuple, Dict


async def auto_assign_vs_roles(repo, room_code: str, gm_pid: Optional[str]) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """
    Auto-assign one drawer per team (excluding GM), everyone else becomes guesser.
    Returns (roles, error_message). roles is {"drawerA": pid, "drawerB": pid}
    """
    players = await repo.list_players(room_code)
    teams = {
        "A": await repo.get_team_members(room_code, "A"),
        "B": await repo.get_team_members(room_code, "B"),
    }

    team_a_members = [p for p in players if p.pid in teams["A"] and p.pid != gm_pid]
    team_b_members = [p for p in players if p.pid in teams["B"] and p.pid != gm_pid]

    if not team_a_members:
        return None, "Team A has no members (excluding GM)"
    if not team_b_members:
        return None, "Team B has no members (excluding GM)"

    prev_roles = await repo.get_roles(room_code)
    prev_drawer_a = prev_roles.get("drawerA")
    prev_drawer_b = prev_roles.get("drawerB")

    def _pick_drawer(members, prev_pid):
        if len(members) <= 1:
            return members[0].pid
        eligible = [p for p in members if p.pid != prev_pid]
        if not eligible:
            return members[0].pid
        return random.choice(eligible).pid

    drawer_a_pid = _pick_drawer(team_a_members, prev_drawer_a)
    drawer_b_pid = _pick_drawer(team_b_members, prev_drawer_b)

    await repo.update_player_fields(room_code, drawer_a_pid, role="drawerA")
    await repo.update_player_fields(room_code, drawer_b_pid, role="drawerB")

    for p in players:
        if p.pid == gm_pid:
            await repo.update_player_fields(room_code, p.pid, role=None)
            continue
        if p.pid == drawer_a_pid or p.pid == drawer_b_pid:
            continue
        if p.pid in teams["A"]:
            await repo.update_player_fields(room_code, p.pid, role="guesserA")
        elif p.pid in teams["B"]:
            await repo.update_player_fields(room_code, p.pid, role="guesserB")
        else:
            await repo.update_player_fields(room_code, p.pid, role=None)

    roles = {"drawerA": drawer_a_pid, "drawerB": drawer_b_pid}
    await repo.set_roles(room_code, roles)
    return roles, None
