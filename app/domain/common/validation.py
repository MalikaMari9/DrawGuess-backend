# app/domain/common/validation.py
from __future__ import annotations

from typing import Optional
from app.store.models import PlayerStore, RoomHeaderStore
from app.domain.common.types import Role, Team

def is_gm(player: Optional[PlayerStore], header: RoomHeaderStore) -> bool:
    """Check if player is GameMaster."""
    return player is not None and header.gm_pid == player.pid

def is_drawer(player: Optional[PlayerStore], team: Optional[Team] = None) -> bool:
    """Check if player is a drawer (optionally for specific team)."""
    if player is None:
        return False
    if team is None:
        return player.role in ["drawer", "drawerA", "drawerB"]
    if team == "A":
        return player.role == "drawerA"
    if team == "B":
        return player.role == "drawerB"
    return False

def is_guesser(player: Optional[PlayerStore], team: Optional[Team] = None) -> bool:
    """Check if player is a guesser (optionally for specific team)."""
    if player is None:
        return False
    if team is None:
        return player.role in ["guesser", "guesserA", "guesserB"]
    if team == "A":
        return player.role == "guesserA"
    if team == "B":
        return player.role == "guesserB"
    return False

def is_on_team(player: Optional[PlayerStore], team: Team) -> bool:
    """Check if player is on the specified team."""
    return player is not None and player.team == team

def has_role(player: Optional[PlayerStore], role: Role) -> bool:
    """Check if player has the specified role."""
    return player is not None and player.role == role

def is_muted(player: Optional[PlayerStore], ts: int) -> bool:
    """Check if player is muted at a given timestamp."""
    return player is not None and int(getattr(player, "muted_until", 0) or 0) > ts

def is_kicked(player: Optional[PlayerStore]) -> bool:
    """Check if player is kicked."""
    return player is not None and bool(getattr(player, "kicked", False))
