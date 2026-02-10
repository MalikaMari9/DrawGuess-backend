# app/domain/lifecycle/handlers.py
from __future__ import annotations

import random
import string
from typing import List, Tuple, Optional, Literal, Dict, Any

from app.util.timeutil import now_ts
from app.store.models import RoomHeaderStore, PlayerStore
from app.transport.protocols import (
    Mode,
    OutgoingEvent,
    OutError,
    OutRoomCreated,
    OutRoomSnapshot,
    OutPlayerJoined,
    OutPlayerLeft,
    OutPhaseChanged,
    InCreateRoom,
    InJoin,
    InLeave,
    InHeartbeat,
    InSnapshot,
    InReconnect,
)

# Returns: (to_sender, to_room)
Result = Tuple[List[OutgoingEvent], List[OutgoingEvent]]


async def _auto_expire_guess_phase(
    *,
    repo,
    room_code: str,
    header: RoomHeaderStore,
    ts: int,
) -> Optional[OutgoingEvent]:
    if header.mode != "VS":
        return None
    if header.state != "IN_ROUND":
        return None

    game = await repo.get_game(room_code)
    if game.get("phase") != "GUESS":
        return None

    guess_end_at_raw = game.get("guess_end_at", 0)
    try:
        guess_end_at = int(guess_end_at_raw) if guess_end_at_raw else 0
    except (TypeError, ValueError):
        guess_end_at = 0

    if not guess_end_at or ts < guess_end_at:
        return None

    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(
        room_code,
        phase="VOTING",
        phase_guesses={},
        votes_next={},
        guess_started_at=0,
        guess_end_at=0,
    )
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")

    return OutPhaseChanged(phase="VOTING", round_no=header.round_no)


def _gen_room_code(n: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(n))

def _should_show_secret(*, roles: dict, viewer_pid: Optional[str], player_role: Optional[str], header: RoomHeaderStore) -> bool:
    if not viewer_pid:
        return False
    if viewer_pid == header.gm_pid:
        return True
    if player_role in ("gm", "drawer", "drawerA", "drawerB"):
        return True
    if roles:
        if viewer_pid in (roles.get("drawerA"), roles.get("drawerB"), roles.get("drawer")):
            return True
    return False


async def _build_snapshot(
    app,
    room_code: str,
    mode: Mode,
    *,
    viewer_pid: Optional[str] = None,
    redact_secret: bool = False,
) -> OutRoomSnapshot:
    """
    Build a full snapshot from Redis.
    Keep it store-driven, not rule-driven.
    """
    repo = app.state.repo

    header = await repo.get_room_header(room_code)
    if header is None:
        # room does not exist (yet)
        return OutRoomSnapshot(
            room={"mode": mode, "state": "WAITING", "cap": 0, "created_at": 0, "last_activity": 0, "gm_pid": None, "round_no": 0},
            players=[],
            roles={},
            round_config={},
            game={},
            ops=[],
        )

    players = await repo.list_players(room_code)
    roles = await repo.get_roles(room_code)
    round_cfg = await repo.get_round_config(room_code)
    # Redact secret_word unless viewer is GM/drawer
    if redact_secret and "secret_word" in round_cfg:
        role = None
        if viewer_pid:
            p = await repo.get_player(room_code, viewer_pid)
            role = getattr(p, "role", None) if p else None
        if not _should_show_secret(roles=roles, viewer_pid=viewer_pid, player_role=role, header=header):
            round_cfg = {k: v for k, v in round_cfg.items() if k != "secret_word"}
    game = await repo.get_game(room_code)
    
    # Include budget in game state for VS mode
    if header.mode == "VS":
        budget = await repo.get_budget(room_code)
        if budget:
            game["budget"] = budget

    # ops depend on mode
    ops_out: List[Dict[str, Any]] = []
    if header.mode == "VS":
        opsA = await repo.get_ops_vs(room_code, "A")
        opsB = await repo.get_ops_vs(room_code, "B")
        # return as a combined list with canvas tag (client can split)
        ops_out = (
            [{"canvas": "A", **op.model_dump()} for op in opsA] +
            [{"canvas": "B", **op.model_dump()} for op in opsB]
        )
    else:
        ops = await repo.get_ops_single(room_code)
        ops_out = [op.model_dump() for op in ops]

    modlog = await repo.get_modlog(room_code)

    return OutRoomSnapshot(
        room=header.model_dump(),
        players=[p.model_dump() for p in players],
        roles=roles,
        round_config=round_cfg,
        game=game,
        ops=ops_out,
        modlog=[m.model_dump() for m in modlog],
    )


# -------------------------
# Handlers
# -------------------------

async def handle_create_room(*, app, room_code: str, pid: Optional[str], msg: InCreateRoom) -> Result:
    """
    create_room does not need pid yet.
    If room_code is provided by URL, we can:
      - treat it as desired code if unused, OR
      - ignore it and generate a new one.
    For simplicity: generate a fresh code always.
    """
    repo = app.state.repo
    ts = now_ts()

    # generate a unique room code
    code = _gen_room_code()
    for _ in range(5):
        if not await repo.room_exists(code):
            break
        code = _gen_room_code()

    header = RoomHeaderStore(
        mode=msg.mode,
        state="WAITING",
        cap=msg.cap,
        created_at=ts,
        last_activity=ts,
        gm_pid=None,
        round_no=0,
    )
    await repo.create_room(code, header)
    await repo.refresh_room_ttl(code, mode=msg.mode)

    return [OutRoomCreated(room_code=code, mode=msg.mode)], []


async def handle_join(*, app, room_code: str, pid: Optional[str], msg: InJoin) -> Result:
    """
    Join:
    - ensure room exists (if not, create with default SINGLE? -> better: error)
    - add/update player entry
    - send snapshot to joiner
    - broadcast player_joined to room
    """
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid for this connection")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message=f"Room {room_code} not found. Create it first.")], []

    # enforce cap
    players = await repo.list_players(room_code)
    if len(players) >= header.cap:
        return [OutError(code="ROOM_FULL", message="Room is full")], []

    # Upsert-ish: if player exists, just mark connected + update name/last_seen
    existing = await repo.get_player(room_code, pid)
    if existing is None:
        p = PlayerStore(
            pid=pid,
            name=msg.name,
            role=None,
            team=None,
            connected=True,
            joined_at=ts,
            last_seen=ts,
            warnings=0,
            muted_until=0,
            kicked=False,
        )
        await repo.add_player(room_code, p)
    else:
        if existing.kicked:
            return [OutError(code="KICKED", message="You have been kicked from this room")], []
        await repo.update_player_fields(room_code, pid, name=msg.name, connected=True, last_seen=ts)

    # update activity + ttl
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    snapshot = await _build_snapshot(app, room_code, header.mode, viewer_pid=pid, redact_secret=True)

    # unicast snapshot to joiner; broadcast join event
    return [snapshot], [OutPlayerJoined(pid=pid, name=msg.name)]


async def handle_snapshot(*, app, room_code: str, pid: Optional[str], msg: InSnapshot) -> Result:
    repo = app.state.repo
    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message=f"Room {room_code} not found")], []

    ts = now_ts()
    phase_event = await _auto_expire_guess_phase(repo=repo, room_code=room_code, header=header, ts=ts)
    if phase_event:
        header = await repo.get_room_header(room_code) or header

    snap = await _build_snapshot(app, room_code, header.mode, viewer_pid=pid, redact_secret=True)
    return [snap], [phase_event] if phase_event else []


async def handle_reconnect(*, app, room_code: str, pid: Optional[str], msg: InReconnect) -> Result:
    """
    Reconnect using an existing pid (stable identity across refresh).
    """
    effective_pid = msg.pid or pid
    if not effective_pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message=f"Room {room_code} not found")], []

    existing = await repo.get_player(room_code, effective_pid)
    if existing is None:
        return [OutError(code="PLAYER_NOT_FOUND", message="Player not found for reconnect")], []

    if getattr(existing, "kicked", False):
        return [OutError(code="KICKED", message="You have been kicked from this room")], []

    await repo.set_player_connected(room_code, effective_pid, True, ts)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    snap = await _build_snapshot(app, room_code, header.mode, viewer_pid=effective_pid, redact_secret=True)
    return [snap], []


async def handle_heartbeat(*, app, room_code: str, pid: Optional[str], msg: InHeartbeat) -> Result:
    """
    Heartbeat keeps presence + TTL alive.
    """
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message=f"Room {room_code} not found")], []

    phase_event = await _auto_expire_guess_phase(repo=repo, room_code=room_code, header=header, ts=ts)

    await repo.set_player_connected(room_code, pid, True, ts)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    # Keep heartbeat quiet (no broadcast spam)
    return [], [phase_event] if phase_event else []


async def handle_leave(*, app, room_code: str, pid: Optional[str], msg: InLeave) -> Result:
    """
    Leave: mark disconnected, remove from active set.
    We do NOT delete player record, because you want reconnect support.
    """
    if not pid:
        return [OutError(code="NO_PID", message="Missing pid")], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [OutError(code="ROOM_NOT_FOUND", message=f"Room {room_code} not found")], []

    await repo.set_player_connected(room_code, pid, False, ts)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    return [], [OutPlayerLeft(pid=pid)]

async def handle_disconnect(*, app, room_code: str, pid: Optional[str]) -> Result:
    """
    Called by transport when WS disconnects unexpectedly.
    Mirrors leave behavior but without requiring a message model.
    """
    if not pid:
        return [], []

    repo = app.state.repo
    ts = now_ts()

    header = await repo.get_room_header(room_code)
    if header is None:
        return [], []

    # mark disconnected (keeps player record)
    await repo.set_player_connected(room_code, pid, False, ts)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    return [], [OutPlayerLeft(pid=pid)]
