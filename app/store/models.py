# app/store/models.py
from __future__ import annotations

from typing import Literal, Optional, Any, Dict
from pydantic import BaseModel, Field


Mode = Literal["SINGLE", "VS"]
RoomState = Literal["WAITING", "ROLE_PICK", "CONFIG", "IN_ROUND", "ROUND_END"]
Phase = Literal["", "FREE", "DRAW", "GUESS"]


class PlayerStore(BaseModel):
    pid: str
    name: str
    role: Optional[str] = None          # "gm" | "drawer" | "guesser" | "drawerA" | ...
    team: Optional[Literal["A", "B"]] = None
    connected: bool = True
    joined_at: int
    last_seen: int
    warnings: int = 0
    muted_until: int = 0


class RoomHeaderStore(BaseModel):
    mode: Mode
    state: RoomState = "WAITING"
    cap: int = 12
    created_at: int
    last_activity: int
    gm_pid: Optional[str] = None
    round_no: int = 0


class DrawOp(BaseModel):
    """
    Keep it compact for Redis LIST.
    You can evolve this as your canvas protocol evolves.
    """
    t: Literal["line", "circle", "clear", "undo", "sabotage"]  # etc
    p: Dict[str, Any] = Field(default_factory=dict)  # payload e.g. points, radius, color, size
    ts: int
    by: str  # pid


class ModLogEntry(BaseModel):
    t: Literal["warn", "mute", "kick"]
    target: str
    by: str
    reason: str = ""
    ts: int
