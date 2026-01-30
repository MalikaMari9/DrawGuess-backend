from __future__ import annotations

from typing import List, Tuple, Optional, Dict

from app.util.timeutil import now_ts
from app.transport.protocols import (
    OutgoingEvent,
    OutError,
    OutTeamsUpdated,
    OutRoomStateChanged,
    InSetTeam,
    InStartRolePick,
)

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

    if header.state != "WAITING":
        return [OutError(code="BAD_STATE", message=f"Cannot start role pick in state {header.state}")], []

    # Minimal start condition: at least 2 connected players
    players = await repo.list_players(room_code)
    connected = [p for p in players if p.connected]
    if len(connected) < 2:
        return [OutError(code="NOT_ENOUGH_PLAYERS", message="Need at least 2 players")], []

    await repo.update_room_fields(room_code, state="ROLE_PICK", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    return [], [OutRoomStateChanged(state="ROLE_PICK")]
