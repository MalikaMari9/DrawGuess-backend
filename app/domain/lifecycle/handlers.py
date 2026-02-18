# app/domain/lifecycle/handlers.py
from __future__ import annotations

import random
import string
from typing import List, Tuple, Optional, Literal, Dict, Any

from app.util.timeutil import now_ts
from app.store.models import RoomHeaderStore, PlayerStore, DrawOp
from app.transport.protocols import (
    Mode,
    OutgoingEvent,
    OutError,
    OutRoomCreated,
    OutRoomSnapshot,
    OutPlayerJoined,
    OutPlayerLeft,
    OutPhaseChanged,
    OutBudgetUpdate,
    OutRoomStateChanged,
    OutGameEnd,
    OutVoteResolved,
    OutOpBroadcast,
    InCreateRoom,
    InJoin,
    InLeave,
    InHeartbeat,
    InSnapshot,
    InReconnect,
    InStartGame,
)

# Returns: (to_sender, to_room)
Result = Tuple[List[OutgoingEvent], List[OutgoingEvent]]



async def _auto_expire_vs_phase(
    *,
    repo,
    room_code: str,
    header: RoomHeaderStore,
    ts: int,
) -> list[OutgoingEvent]:
    if header.mode != "VS":
        return []
    if header.state != "IN_GAME":
        return []

    from app.domain.vs.handlers_common import auto_advance_vs_phase
    return await auto_advance_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)


async def _auto_expire_single_game(
    *,
    repo,
    room_code: str,
    header: RoomHeaderStore,
    ts: int,
) -> list[OutgoingEvent]:
    if header.mode != "SINGLE":
        return []
    if header.state != "IN_GAME":
        return []

    game = await repo.get_game(room_code)
    game_end_at_raw = game.get("game_end_at", 0)
    try:
        game_end_at = int(game_end_at_raw) if game_end_at_raw else 0
    except (TypeError, ValueError):
        game_end_at = 0

    if not game_end_at or ts < game_end_at:
        return []

    from app.domain.common.roles import clear_all_roles
    await clear_all_roles(repo, room_code)
    await repo.vote_next_clear(room_code)
    await repo.set_game_fields(
        room_code,
        phase="VOTING",
        winner_pid="",
        end_reason="TIMEOUT",
        game_end_at=ts,
        votes_next={},
        clear_ops_at=ts + 5,
    )
    await repo.update_room_fields(room_code, state="GAME_END", last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="SINGLE")

    round_cfg = await repo.get_round_config(room_code)
    word = round_cfg.get("secret_word", "")

    return [
        OutRoomStateChanged(state="GAME_END"),
        OutPhaseChanged(phase="VOTING", round_no=header.round_no),
        OutGameEnd(winner=None, word=word, game_no=header.game_no, round_no=header.round_no, reason="TIMEOUT"),
    ]


async def _auto_clear_ops_after_game(
    *,
    repo,
    room_code: str,
    header: RoomHeaderStore,
    ts: int,
) -> list[OutgoingEvent]:
    game = await repo.get_game(room_code)
    clear_ops_at_raw = game.get("clear_ops_at", 0)
    try:
        clear_ops_at = int(clear_ops_at_raw) if clear_ops_at_raw else 0
    except (TypeError, ValueError):
        clear_ops_at = 0

    if not clear_ops_at or ts < clear_ops_at:
        return []

    await repo.clear_ops(room_code, mode=header.mode)
    await repo.set_game_fields(room_code, clear_ops_at=0)

    events: list[OutgoingEvent] = []
    clear_op = DrawOp(t="clear", p={}, ts=ts, by="system")

    if header.mode == "VS":
        for team in ("A", "B"):
            await repo.append_op_vs(room_code, team, clear_op)
            events.append(OutOpBroadcast(op=clear_op.model_dump(), canvas=team, by="system"))
    else:
        await repo.append_op_single(room_code, clear_op)
        events.append(OutOpBroadcast(op=clear_op.model_dump(), canvas=None, by="system"))

    return events


async def _auto_resolve_vs_vote_window(
    *,
    repo,
    room_code: str,
    header: RoomHeaderStore,
    ts: int,
) -> list[OutgoingEvent]:
    if header.mode != "VS":
        return []
    if header.state != "GAME_END":
        return []

    game = await repo.get_game(room_code)
    if game.get("phase") != "VOTING":
        return []

    vote_end_at_raw = game.get("vote_end_at", 0)
    try:
        vote_end_at = int(vote_end_at_raw) if vote_end_at_raw else 0
    except (TypeError, ValueError):
        vote_end_at = 0

    if not vote_end_at or ts < vote_end_at:
        return []

    eligible = list(await repo.get_active_pids(room_code))
    if not eligible:
        from app.domain.common.roles import strip_identity
        await strip_identity(repo, room_code)
        await repo.set_game_fields(room_code, vote_end_at=0, vote_outcome="NO", phase="FINAL")
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")
        ev = OutVoteResolved(outcome="NO", ts=ts, yes_count=0, eligible=0)
        return [ev]

    votes = game.get("votes_next") or {}
    if not isinstance(votes, dict):
        votes = {}

    yes_count = sum(1 for p in eligible if votes.get(p) == "yes")
    threshold = (len(eligible) // 2) + 1

    if yes_count >= threshold:
        await repo.set_game_fields(
            room_code,
            reset_to_waiting_at=ts + 2,
            vote_end_at=0,
            vote_outcome="YES",
        )
        await repo.update_room_fields(room_code, last_activity=ts)
        await repo.refresh_room_ttl(room_code, mode="VS")
        ev = OutVoteResolved(outcome="YES", ts=ts, yes_count=yes_count, eligible=len(eligible))
        return [ev]

    from app.domain.common.roles import strip_identity
    await strip_identity(repo, room_code)
    await repo.set_game_fields(room_code, phase="FINAL", vote_end_at=0, vote_outcome="NO")
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode="VS")
    ev = OutVoteResolved(outcome="NO", ts=ts, yes_count=yes_count, eligible=len(eligible))
    return [ev]


async def _auto_reset_vs_to_waiting_after_vote_yes(
    *,
    repo,
    room_code: str,
    header: RoomHeaderStore,
    ts: int,
) -> list[OutgoingEvent]:
    if header.mode != "VS":
        return []
    if header.state != "GAME_END":
        return []

    game = await repo.get_game(room_code)
    if game.get("phase") != "VOTING":
        return []

    reset_at_raw = game.get("reset_to_waiting_at", 0)
    try:
        reset_at = int(reset_at_raw) if reset_at_raw else 0
    except (TypeError, ValueError):
        reset_at = 0

    if not reset_at or ts < reset_at:
        return []

    from app.domain.common.roles import strip_identity
    await strip_identity(repo, room_code)
    await repo.vote_next_clear(room_code)
    await repo.clear_round_config(room_code)

    # Keep clear_ops_at intact so the end-screen drawing clears on schedule.
    clear_ops_at_raw = game.get("clear_ops_at", 0)
    try:
        clear_ops_at = int(clear_ops_at_raw) if clear_ops_at_raw else 0
    except (TypeError, ValueError):
        clear_ops_at = 0

    await repo.set_game_fields(
        room_code,
        phase="",
        votes_next={},
        winner_team="",
        winner_pid="",
        end_reason="",
        draw_end_at=0,
        guess_end_at=0,
        team_guessed={},
        team_guess_result={},
        game_end_at=0,
        reset_to_waiting_at=0,
        clear_ops_at=clear_ops_at,
    )
    await repo.update_room_fields(room_code, state="WAITING", round_no=0, last_activity=ts, countdown_end_at=0)
    await repo.refresh_room_ttl(room_code, mode="VS")

    return [OutRoomStateChanged(state="WAITING")]


async def _auto_start_from_countdown(
    *,
    app,
    room_code: str,
    header: RoomHeaderStore,
    ts: int,
) -> list[OutgoingEvent]:
    if header.state != "CONFIG":
        return []

    countdown_end_at = int(getattr(header, "countdown_end_at", 0) or 0)
    if not countdown_end_at or ts < countdown_end_at:
        return []

    if header.mode == "VS":
        from app.domain.vs.handlers_start_round import handle_vs_start_game
        _, to_room = await handle_vs_start_game(app=app, room_code=room_code, pid=header.gm_pid, msg=InStartGame())
        return to_room

    if header.mode == "SINGLE":
        from app.domain.single.handlers_start import handle_single_start_game
        _, to_room = await handle_single_start_game(app=app, room_code=room_code, pid=header.gm_pid, msg=InStartGame())
        return to_room

    return []


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
            server_ts=now_ts(),
        )

    players = await repo.list_players(room_code)
    roles = await repo.get_roles(room_code)
    round_cfg = await repo.get_round_config(room_code)
    # Redact secret_word unless viewer is GM/drawer
    if redact_secret and "secret_word" in round_cfg:
        # During GAME_END, the end screen should reveal the word to everyone.
        if getattr(header, "state", None) == "GAME_END":
            pass
        else:
            role = None
            if viewer_pid:
                p = await repo.get_player(room_code, viewer_pid)
                role = getattr(p, "role", None) if p else None
            if not _should_show_secret(roles=roles, viewer_pid=viewer_pid, player_role=role, header=header):
                round_cfg = {k: v for k, v in round_cfg.items() if k != "secret_word"}
    game = await repo.get_game(room_code)
    
    # Include budget/cooldown in game state for VS mode
    if header.mode == "VS":
        budget = await repo.get_budget(room_code)
        if budget:
            game["budget"] = budget
        cooldown = await repo.get_cooldown(room_code)
        if cooldown:
            game["cooldown"] = cooldown

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
        server_ts=now_ts(),
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

    # Ensure GM has role set (covers reconnects / header gm_pid already set)
    if header.gm_pid and header.gm_pid == pid:
        await repo.update_player_fields(room_code, pid, role="gm")

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
    vote_events = await _auto_resolve_vs_vote_window(repo=repo, room_code=room_code, header=header, ts=ts)
    if vote_events:
        header = await repo.get_room_header(room_code) or header
    reset_events = await _auto_reset_vs_to_waiting_after_vote_yes(repo=repo, room_code=room_code, header=header, ts=ts)
    if reset_events:
        header = await repo.get_room_header(room_code) or header
    auto_start_events = await _auto_start_from_countdown(app=app, room_code=room_code, header=header, ts=ts)
    if auto_start_events:
        header = await repo.get_room_header(room_code) or header
    vs_phase_events = await _auto_expire_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)
    single_events = await _auto_expire_single_game(repo=repo, room_code=room_code, header=header, ts=ts)
    clear_events = await _auto_clear_ops_after_game(repo=repo, room_code=room_code, header=header, ts=ts)
    if vote_events or reset_events or auto_start_events or vs_phase_events or single_events or clear_events:
        header = await repo.get_room_header(room_code) or header

    snap = await _build_snapshot(app, room_code, header.mode, viewer_pid=pid, redact_secret=True)
    events = []
    events.extend(vote_events)
    events.extend(reset_events)
    events.extend(auto_start_events)
    events.extend(vs_phase_events)
    events.extend(single_events)
    events.extend(clear_events)
    return [*events, snap], events


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

    vote_events = await _auto_resolve_vs_vote_window(repo=repo, room_code=room_code, header=header, ts=ts)
    if vote_events:
        header = await repo.get_room_header(room_code) or header
    reset_events = await _auto_reset_vs_to_waiting_after_vote_yes(repo=repo, room_code=room_code, header=header, ts=ts)
    if reset_events:
        header = await repo.get_room_header(room_code) or header

    auto_start_events = await _auto_start_from_countdown(app=app, room_code=room_code, header=header, ts=ts)
    if auto_start_events:
        header = await repo.get_room_header(room_code) or header

    snap = await _build_snapshot(app, room_code, header.mode, viewer_pid=effective_pid, redact_secret=True)
    events = [*vote_events, *reset_events, *auto_start_events]
    return [*events, snap], events


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

    vote_events = await _auto_resolve_vs_vote_window(repo=repo, room_code=room_code, header=header, ts=ts)
    if vote_events:
        header = await repo.get_room_header(room_code) or header
    reset_events = await _auto_reset_vs_to_waiting_after_vote_yes(repo=repo, room_code=room_code, header=header, ts=ts)
    if reset_events:
        header = await repo.get_room_header(room_code) or header

    auto_start_events = await _auto_start_from_countdown(app=app, room_code=room_code, header=header, ts=ts)
    if auto_start_events:
        header = await repo.get_room_header(room_code) or header
    vs_phase_events = await _auto_expire_vs_phase(repo=repo, room_code=room_code, header=header, ts=ts)
    single_events = await _auto_expire_single_game(repo=repo, room_code=room_code, header=header, ts=ts)
    clear_events = await _auto_clear_ops_after_game(repo=repo, room_code=room_code, header=header, ts=ts)

    await repo.set_player_connected(room_code, pid, True, ts)
    await repo.update_room_fields(room_code, last_activity=ts)
    await repo.refresh_room_ttl(room_code, mode=header.mode)

    events = []
    events.extend(vote_events)
    events.extend(reset_events)
    events.extend(auto_start_events)
    events.extend(vs_phase_events)
    events.extend(single_events)
    events.extend(clear_events)
    return list(events), events


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
