from __future__ import annotations

from typing import List, Optional, Tuple

from app.transport.protocols import (
    InSetVsConfig,
    OutError,
    OutRoomSnapshot,
    OutRoomStateChanged,
)
from app.util.timeutil import now_ts

Outgoing = List[object]
Result = Tuple[Outgoing, Outgoing]


async def _snapshot_for(app, room_code: str, *, viewer_pid: Optional[str]) -> OutRoomSnapshot:
    from app.domain.lifecycle.handlers import _build_snapshot
    header = await app.state.repo.get_room_header(room_code)
    mode = header.mode if header else "VS"
    return await _build_snapshot(app, room_code, mode, viewer_pid=viewer_pid, redact_secret=True)


async def handle_vs_set_round_config(*, app, room_code: str, pid: Optional[str], msg: InSetVsConfig) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []
    if header.mode != "VS":
        return [OutError(code="NOT_VS", message="This handler is for VS mode only")], []

    if header.gm_pid != pid:
        return [OutError(code="NOT_GM", message="Only GameMaster can set config")], []

    if header.state not in ("ROLE_PICK", "CONFIG"):
        return [OutError(code="BAD_STATE", message=f"Cannot set config in state {header.state}")], []

    await repo.set_round_config(
        room_code,
        {
            "secret_word": msg.secret_word.strip(),
            "time_limit_sec": int(msg.time_limit_sec),
            "strokes_per_phase": int(msg.strokes_per_phase),
            "guess_window_sec": int(msg.guess_window_sec),
            "config_ready": 1,
        },
    )

    await repo.update_room_fields(room_code, state="CONFIG", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    to_sender = [OutRoomStateChanged(state="CONFIG"), await _snapshot_for(app, room_code, viewer_pid=pid)]
    to_room = [OutRoomStateChanged(state="CONFIG")]
    players = await repo.list_players(room_code)
    for p in players:
        if p.pid == pid:
            continue
        if not getattr(p, "connected", True):
            continue
        snap = await _snapshot_for(app, room_code, viewer_pid=p.pid)
        to_room.append({**snap.model_dump(), "targets": [p.pid]})
    return to_sender, to_room
