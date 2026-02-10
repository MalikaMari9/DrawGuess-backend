from __future__ import annotations

from typing import List, Tuple, Optional, Dict
import random

from app.util.timeutil import now_ts
from app.transport.protocols import (
    OutgoingEvent,
    OutError,
    OutTeamsUpdated,
    OutRoomStateChanged,
    OutRolesAssigned,
    InSetTeam,
    InStartRolePick,
)
from app.domain.vs.roles import auto_assign_vs_roles
from app.domain.helpers.role_pick import assign_single_roles

Result = Tuple[List[OutgoingEvent], List[OutgoingEvent]]


async def _build_teams(repo, room_code: str) -> Dict[str, List[str]]:
    A = sorted(list(await repo.get_team_members(room_code, "A")))
    B = sorted(list(await repo.get_team_members(room_code, "B")))
    return {"A": A, "B": B}


async def handle_set_team(*, app, room_code: str, pid: Optional[str], msg: InSetTeam) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message=f"Room {room_code} not found")], []

    if header.mode != "VS":
        return [OutError(code="NOT_VS", message="set_team is only for VS rooms")], []

    if header.state != "WAITING":
        return [OutError(code="BAD_STATE", message=f"Cannot set team in state {header.state}")], []

    await repo.set_team(room_code, pid, msg.team)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    teams = await _build_teams(repo, room_code)
    return [], [OutTeamsUpdated(teams=teams)]


async def handle_start_role_pick(*, app, room_code: str, pid: Optional[str], msg: InStartRolePick) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message=f"Room {room_code} not found")], []

    if header.state not in ["WAITING", "ROLE_PICK"]:
        return [OutError(code="BAD_STATE", message=f"Cannot start role pick in state {header.state}")], []


    # Check minimum players based on mode
    players = await repo.list_players(room_code)
    connected = [p for p in players if p.connected]
    
    if header.mode == "VS":
        if len(connected) < 5:
            return [OutError(code="NOT_ENOUGH_PLAYERS", message="VS mode requires at least 5 players")], []
    else:
        if len(connected) < 3:
            return [OutError(code="NOT_ENOUGH_PLAYERS", message="SINGLE mode requires at least 3 players")], []

    # Auto-assign GM if none exists yet (random among connected players)
    gm_pid = header.gm_pid
    if gm_pid is None and connected:
        gm_pid = random.choice(connected).pid
        await repo.update_room_fields(room_code, gm_pid=gm_pid)

    # VS mode: auto-assign drawers/guessers and move straight to CONFIG
    if header.mode == "VS":
        roles, error = await auto_assign_vs_roles(repo, room_code, gm_pid)
        if error:
            return [OutError(code="ROLE_ASSIGN_FAILED", message=error)], []

        await repo.update_room_fields(room_code, state="CONFIG", last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode=header.mode)

        return [], [
            OutRoomStateChanged(state="CONFIG"),
            OutRolesAssigned(mode="VS", roles=roles),
        ]

    # SINGLE: auto-assign GM + drawer + guessers, then move to ROLE_PICK
    gm_pid, drawer_pid, guesser_pids = await assign_single_roles(
        repo=repo,
        room_code=room_code,
        connected=connected,
        gm_pid=gm_pid,
        seed=f"{room_code}:{ts}",
    )

    await repo.update_room_fields(room_code, state="ROLE_PICK", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    return [], [
        OutRoomStateChanged(state="ROLE_PICK"),
        OutRolesAssigned(mode="SINGLE", roles={"gm_pid": gm_pid, "drawer_pid": drawer_pid, "guesser_pids": guesser_pids}),
    ]
