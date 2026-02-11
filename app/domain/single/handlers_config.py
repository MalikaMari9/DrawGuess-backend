# app/domain/single/handlers_config.py
from __future__ import annotations

from typing import List, Optional, Tuple

from app.transport.protocols import (
    InSetRoundConfig,
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
    mode = header.mode if header else "SINGLE"
    return await _build_snapshot(app, room_code, mode, viewer_pid=viewer_pid, redact_secret=True)


async def handle_single_set_round_config(*, app, room_code: str, pid: Optional[str], msg: InSetRoundConfig) -> Result:
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
        return [OutError(code="NOT_GM", message="Only GM can set round config")], []

    if header.state not in ("ROLE_PICK", "CONFIG"):
        return [OutError(code="BAD_STATE", message=f"Cannot set config in state {header.state}")], []

    await repo.set_round_config(
        room_code,
        {
            "secret_word": msg.secret_word.strip(),
            "stroke_limit": int(msg.stroke_limit),
            "time_limit_sec": int(msg.time_limit_sec),
        },
    )

    await repo.update_room_fields(room_code, state="CONFIG", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    to_sender = [OutRoomStateChanged(state="CONFIG"), await _snapshot_for(app, room_code, viewer_pid=pid)]
    to_room = [OutRoomStateChanged(state="CONFIG"), await _snapshot_for(app, room_code, viewer_pid=None)]
    return to_sender, to_room
