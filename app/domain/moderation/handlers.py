# app/domain/moderation/handlers.py
from __future__ import annotations

from typing import Optional, List, Tuple

from app.domain.common.validation import is_gm
from app.store.models import ModLogEntry
from app.transport.protocols import (
    InModeration,
    OutError,
    OutModLogEntry,
    OutPlayerKicked,
    OutPlayerUpdated,
    OutgoingEvent,
)
from app.util.timeutil import now_ts

Result = Tuple[List[OutgoingEvent], List[OutgoingEvent]]


async def handle_moderation(*, app, room_code: str, pid: Optional[str], msg: InModeration) -> Result:
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message="Room not found")], []

    actor = await repo.get_player(room_code, pid)
    if not is_gm(actor, header):
        return [OutError(code="NOT_GM", message="Only GameMaster can moderate")], []

    target = await repo.get_player(room_code, msg.target)
    if target is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Target player not found")], []

    action = msg.action
    reason = msg.reason or ""

    if action == "warn":
        await repo.update_player_fields(room_code, msg.target, warnings=target.warnings + 1)

    elif action == "mute":
        if not msg.duration_sec or msg.duration_sec <= 0:
            return [OutError(code="BAD_MUTE", message="duration_sec is required for mute")], []
        muted_until = ts + int(msg.duration_sec)
        await repo.update_player_fields(room_code, msg.target, muted_until=muted_until)

    elif action == "kick":
        # Mark disconnected and remove from active set
        await repo.set_player_connected(room_code, msg.target, False, ts)
        await repo.update_player_fields(room_code, msg.target, kicked=True)

    entry = ModLogEntry(t=action, target=msg.target, by=pid, reason=reason, ts=ts)
    await repo.append_modlog(room_code, entry)

    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    updated = await repo.get_player(room_code, msg.target)
    if updated is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Target player not found")], []

    to_room: List[OutgoingEvent] = [
        OutPlayerUpdated(player=updated.model_dump()),
        OutModLogEntry(entry=entry.model_dump()),
    ]

    if action == "kick":
        to_room.append(OutPlayerKicked(pid=msg.target, reason=reason))
        # Immediately close target's websocket (if connected)
        wsman = getattr(app.state, "wsman", None)
        if wsman is not None:
            await wsman.close_pid(room_code, msg.target, code=4001, reason="kicked")

    return [], to_room

