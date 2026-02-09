# app/transport/protocols.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ValidationError


# =========================
# Shared enums / literals
# =========================

Mode = Literal["SINGLE", "VS"]
Team = Literal["A", "B"]

RoomState = Literal["WAITING", "ROLE_PICK", "CONFIG", "IN_ROUND", "ROUND_END"]
Phase = Literal["", "FREE", "DRAW", "GUESS", "VOTING"]


# =========================
# Incoming (Client -> Server)
# =========================

class InBase(BaseModel):
    type: str


# ---- Lifecycle ----

class InCreateRoom(InBase):
    type: Literal["create_room"] = "create_room"
    mode: Mode
    cap: int = 8


class InJoin(InBase):
    type: Literal["join"] = "join"
    name: str = Field(min_length=1, max_length=24)


class InLeave(InBase):
    type: Literal["leave"] = "leave"


class InHeartbeat(InBase):
    type: Literal["heartbeat"] = "heartbeat"


class InSnapshot(InBase):
    type: Literal["snapshot"] = "snapshot"


# ---- Shared gameplay inputs ----

class InGuess(InBase):
    type: Literal["guess"] = "guess"
    text: str = Field(min_length=1, max_length=80)


class InDrawOp(InBase):
    """
    Single mode: no canvas field.
    VS mode: include canvas="A"/"B".
    """
    type: Literal["draw_op"] = "draw_op"
    op: Dict[str, Any]
    canvas: Optional[Team] = None


class InVoteNext(InBase):
    type: Literal["vote_next"] = "vote_next"
    vote: Literal["yes", "no"] = "yes"


class InPhaseTick(InBase):
    type: Literal["phase_tick"] = "phase_tick"


class InSabotage(InBase):
    type: Literal["sabotage"] = "sabotage"
    target: Team
    op: Dict[str, Any]

class InModeration(InBase):
    type: Literal["moderation"] = "moderation"
    action: Literal["warn", "mute", "kick"]
    target: str
    reason: Optional[str] = ""
    duration_sec: Optional[int] = None

# ---- Lobby/VS Mode inputs ----

class InSetTeam(InBase):
    type: Literal["set_team"] = "set_team"
    team: Team  # "A" | "B"


class InStartRolePick(InBase):
    type: Literal["start_role_pick"] = "start_role_pick"


class InAssignRoles(InBase):
    type: Literal["assign_roles"] = "assign_roles"
    drawerA: Optional[str] = None  # pid, if None auto-assign
    drawerB: Optional[str] = None  # pid, if None auto-assign


class InStartRound(InBase):
    type: Literal["start_round"] = "start_round"
    # Secret word for this round. Must NOT be broadcast to non-GM clients.
    secret_word: str = Field(min_length=1, max_length=50)
    # Total time limit for the drawing phase (seconds). Example: 240 (4 minutes).
    time_limit_sec: int = Field(default=240, ge=60, le=900)
    # Strokes per DRAW phase for each team (VS mode): 3–5 as per spec.
    strokes_per_phase: int = Field(default=3, ge=3, le=5)
    # Optional guess window length (seconds) for VS mode, e.g. 10s.
    guess_window_sec: int = Field(default=10, ge=5, le=60)


# Union of all incoming messages you support right now
IncomingMessage = Union[
    InCreateRoom,
    InJoin,
    InLeave,
    InHeartbeat,
    InSnapshot,
    InGuess,
    InDrawOp,
    InVoteNext,
    InPhaseTick,
    InSabotage,
    InModeration,
    InSetTeam,
    InStartRolePick,
    InAssignRoles,
    InStartRound,
]


# =========================
# Outgoing (Server -> Client)
# =========================

class OutBase(BaseModel):
    type: str


class OutError(OutBase):
    type: Literal["error"] = "error"
    code: str
    message: str


class OutRoomSnapshot(OutBase):
    type: Literal["room_snapshot"] = "room_snapshot"
    room: Dict[str, Any]
    players: List[Dict[str, Any]]
    roles: Dict[str, Any] = Field(default_factory=dict)
    round_config: Dict[str, Any] = Field(default_factory=dict)
    game: Dict[str, Any] = Field(default_factory=dict)
    ops: List[Dict[str, Any]] = Field(default_factory=list)
    modlog: List[Dict[str, Any]] = Field(default_factory=list)


class OutRoomCreated(OutBase):
    type: Literal["room_created"] = "room_created"
    room_code: str
    mode: Mode


class OutPlayerJoined(OutBase):
    type: Literal["player_joined"] = "player_joined"
    pid: str
    name: str


class OutPlayerLeft(OutBase):
    type: Literal["player_left"] = "player_left"
    pid: str


class OutOpBroadcast(OutBase):
    type: Literal["op_broadcast"] = "op_broadcast"
    op: Dict[str, Any]
    canvas: Optional[Team] = None
    by: str


# Moved to end of file


# =========================
# Parser helpers
# =========================

# A small map so we can parse by "type" quickly (simple & readable)
_INCOMING_BY_TYPE = {
    "create_room": InCreateRoom,
    "join": InJoin,
    "leave": InLeave,
    "heartbeat": InHeartbeat,
    "snapshot": InSnapshot,
    "guess": InGuess,
    "draw_op": InDrawOp,
    "vote_next": InVoteNext,
    "phase_tick": InPhaseTick,
    "sabotage": InSabotage,
    "moderation": InModeration,
    "set_team": InSetTeam,
    "start_role_pick": InStartRolePick,
    "assign_roles": InAssignRoles,
    "start_round": InStartRound,
}


def parse_incoming(payload: Dict[str, Any]) -> IncomingMessage:
    """
    Convert raw dict -> validated message model.
    Raises ValidationError if invalid.
    """
    t = payload.get("type")
    if not isinstance(t, str):
        raise ValidationError.from_exception_data(
            title="IncomingMessage",
            line_errors=[{"loc": ("type",), "msg": "Missing/invalid type", "type": "value_error"}],
        )

    cls = _INCOMING_BY_TYPE.get(t)
    if cls is None:
        raise ValidationError.from_exception_data(
            title="IncomingMessage",
            line_errors=[{"loc": ("type",), "msg": f"Unknown message type: {t}", "type": "value_error"}],
        )

    return cls.model_validate(payload)


# =========================
# Lobby/VS Mode Events
# =========================

class OutTeamsUpdated(OutBase):
    type: Literal["teams_updated"] = "teams_updated"
    teams: Dict[str, List[str]]  # {"A":[pid...], "B":[pid...]}

class OutRoomStateChanged(OutBase):
    type: Literal["room_state_changed"] = "room_state_changed"
    state: RoomState


class OutRolesAssigned(OutBase):
    type: Literal["roles_assigned"] = "roles_assigned"
    roles: Dict[str, str]  # {"drawerA": pid, "drawerB": pid}

class OutPlayerUpdated(OutBase):
    type: Literal["player_updated"] = "player_updated"
    player: Dict[str, Any]

class OutModLogEntry(OutBase):
    type: Literal["modlog_entry"] = "modlog_entry"
    entry: Dict[str, Any]

class OutPlayerKicked(OutBase):
    type: Literal["player_kicked"] = "player_kicked"
    pid: str
    reason: str = ""

# ---- VS Mode Events ----

class OutPhaseChanged(OutBase):
    type: Literal["phase_changed"] = "phase_changed"
    phase: Phase
    round_no: int


class OutGuessResult(OutBase):
    type: Literal["guess_result"] = "guess_result"
    correct: bool
    team: Optional[Team] = None
    text: str
    by: str


class OutBudgetUpdate(OutBase):
    type: Literal["budget_update"] = "budget_update"
    budget: Dict[str, int]  # {"A": 3, "B": 2} or {"stroke_remaining": 5}


class OutSabotageUsed(OutBase):
    type: Literal["sabotage_used"] = "sabotage_used"
    by: str
    target: Team
    cooldown_until: int


class OutRoundEnd(OutBase):
    type: Literal["round_end"] = "round_end"
    winner: Optional[Team] = None
    word: str
    round_no: int


# Update OutgoingEvent union
OutgoingEvent = Union[
    OutError,
    OutRoomSnapshot,
    OutRoomCreated,
    OutPlayerJoined,
    OutPlayerLeft,
    OutOpBroadcast,
    OutPlayerUpdated,
    OutModLogEntry,
    OutPlayerKicked,
    OutTeamsUpdated,
    OutRoomStateChanged,
    OutRolesAssigned,
    OutPhaseChanged,
    OutGuessResult,
    OutBudgetUpdate,
    OutSabotageUsed,
    OutRoundEnd,
]
