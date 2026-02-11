# app/domain/single/handlers_start.py
from __future__ import annotations

from typing import List, Optional, Tuple

from app.transport.protocols import (
    InStartGame,
    OutError,
    OutRoomSnapshot,
    OutRoomStateChanged,
    OutPhaseChanged,
)
from app.util.timeutil import now_ts

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]


async def _snapshot_for(app, room_code: str, *, viewer_pid: Optional[str]) -> OutRoomSnapshot:
    from app.domain.lifecycle.handlers import _build_snapshot
    header = await app.state.repo.get_room_header(room_code)
    mode = header.mode if header else "SINGLE"
    return await _build_snapshot(app, room_code, mode, viewer_pid=viewer_pid, redact_secret=True)


async def handle_single_start_game(*, app, room_code: str, pid: Optional[str], msg: InStartGame) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []
    if header.mode != "SINGLE":
        return [OutError(code="NOT_SINGLE", message="This handler is for SINGLE mode only")], []

    player = await repo.get_player(room_code, pid)
    if not player or getattr(player, "role", None) != "gm":
        return [OutError(code="NOT_GM", message="Only GM can start the game")], []

    if header.state not in ("CONFIG", "ROLE_PICK"):
        return [OutError(code="BAD_STATE", message=f"Cannot start game in state {header.state}")], []

    cfg = await repo.get_round_config(room_code)
    secret = (cfg.get("secret_word") or "").strip()
    stroke_limit = int(cfg.get("stroke_limit") or 0)
    time_limit_sec = int(cfg.get("time_limit_sec") or 0)
    if not secret or stroke_limit <= 0 or time_limit_sec <= 0:
        return [OutError(code="CONFIG_MISSING", message="GM must set secret word, stroke limit, and time limit first")], []

    roles = await repo.get_roles(room_code)
    drawer_pid = roles.get("drawer") or ""
    if not drawer_pid:
        return [OutError(code="NO_DRAWER", message="Drawer not assigned")], []

    await repo.set_game_fields(
        room_code,
        phase="DRAW",
        drawer_pid=drawer_pid,
        round_started_at=ts,
        round_end_at=ts + time_limit_sec,
        stroke_limit=stroke_limit,
        strokes_left=stroke_limit,
        votes_next={},
    )

    round_no = header.round_no + 1
    await repo.update_room_fields(room_code, state="IN_ROUND", last_activity=ts, round_no=round_no)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    to_sender = [
        OutRoomStateChanged(state="IN_ROUND"),
        OutPhaseChanged(phase="DRAW", round_no=round_no),
        await _snapshot_for(app, room_code, viewer_pid=pid),
    ]
    to_room = [
        OutRoomStateChanged(state="IN_ROUND"),
        OutPhaseChanged(phase="DRAW", round_no=round_no),
        await _snapshot_for(app, room_code, viewer_pid=None),
    ]
    return to_sender, to_room
