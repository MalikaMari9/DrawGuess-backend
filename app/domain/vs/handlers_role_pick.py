# app/domain/vs/handlers_role_pick.py
from __future__ import annotations

import random
from typing import Optional

from .handlers_common import Result
from app.transport.protocols import OutError, OutRoomStateChanged, OutRolesAssigned, InAssignRoles
from app.util.timeutil import now_ts


async def handle_vs_role_pick(*, app, room_code: str, pid: Optional[str], msg: InAssignRoles) -> Result:
    """
    Assign roles for VS mode.
    GM assigns drawerA and drawerB, rest become guessers.
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

    if header.state != "ROLE_PICK":
        return [OutError(code="BAD_STATE", message=f"Cannot pick roles in state {header.state}")], []

    # Only GM can assign roles
    if header.gm_pid != pid:
        return [OutError(code="NOT_GM", message="Only GameMaster can assign roles")], []

    players = await repo.list_players(room_code)
    teams = {
        "A": await repo.get_team_members(room_code, "A"),
        "B": await repo.get_team_members(room_code, "B"),
    }

    # Get current roles
    roles = await repo.get_roles(room_code)

    # Find drawers for each team (exclude GM from being drawer)
    drawer_a_pid = roles.get("drawerA")
    drawer_b_pid = roles.get("drawerB")

    # Get team members excluding GM
    team_a_members = [p for p in players if p.pid in teams["A"] and p.pid != header.gm_pid]
    team_b_members = [p for p in players if p.pid in teams["B"] and p.pid != header.gm_pid]

    # Assign Team A drawer
    if not drawer_a_pid:
        if msg.drawerA:
            # Use provided drawer (must be in team A and not GM)
            if msg.drawerA in teams["A"] and msg.drawerA != header.gm_pid:
                drawer_a_pid = msg.drawerA
            else:
                return [OutError(code="INVALID_DRAWER", message="Drawer must be in Team A and not be GM")], []
        else:
            # Auto-assign: pick random from Team A (excluding GM)
            if team_a_members:
                drawer_a_pid = random.choice(team_a_members).pid
            else:
                return [OutError(code="NO_TEAM_A", message="Team A has no members (excluding GM)")], []

        await repo.update_player_fields(room_code, drawer_a_pid, role="drawerA")
        roles["drawerA"] = drawer_a_pid

    # Assign Team B drawer
    if not drawer_b_pid:
        if msg.drawerB:
            # Use provided drawer (must be in team B and not GM)
            if msg.drawerB in teams["B"] and msg.drawerB != header.gm_pid:
                drawer_b_pid = msg.drawerB
            else:
                return [OutError(code="INVALID_DRAWER", message="Drawer must be in Team B and not be GM")], []
        else:
            # Auto-assign: pick random from Team B (excluding GM)
            if team_b_members:
                drawer_b_pid = random.choice(team_b_members).pid
            else:
                return [OutError(code="NO_TEAM_B", message="Team B has no members (excluding GM)")], []

        await repo.update_player_fields(room_code, drawer_b_pid, role="drawerB")
        roles["drawerB"] = drawer_b_pid

    # Assign guessers to all remaining players (excluding GM and drawers)
    for p in players:
        # Skip GM - GM has no team/role assignment
        if p.pid == header.gm_pid:
            continue

        # Skip already assigned drawers
        if p.pid == drawer_a_pid or p.pid == drawer_b_pid:
            continue

        # Assign guesser role based on team
        if p.pid in teams["A"]:
            await repo.update_player_fields(room_code, p.pid, role="guesserA")
        elif p.pid in teams["B"]:
            await repo.update_player_fields(room_code, p.pid, role="guesserB")
        # If player has no team, they remain without role (shouldn't happen in VS mode)

    await repo.set_roles(room_code, roles)
    await repo.update_room_fields(room_code, state="CONFIG", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    # Broadcast role assignments to all players
    return [], [
        OutRoomStateChanged(state="CONFIG"),
        OutRolesAssigned(mode="VS", roles={k: v for k, v in roles.items() if k in ["drawerA", "drawerB"]}),
    ]
