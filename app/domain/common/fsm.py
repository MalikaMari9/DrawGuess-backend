# app/domain/common/fsm.py
from __future__ import annotations

from typing import Literal
from app.domain.common.types import RoomState, Phase

def can_transition_to(current: RoomState, target: RoomState) -> bool:
    """
    Validate state transitions.
    """
    transitions: dict[RoomState, list[RoomState]] = {
        "WAITING": ["ROLE_PICK", "WAITING"],
        "ROLE_PICK": ["CONFIG", "WAITING"],
        "CONFIG": ["IN_ROUND", "WAITING"],
        "IN_ROUND": ["ROUND_END", "WAITING"],
        "ROUND_END": ["CONFIG", "WAITING", "ROLE_PICK"],
    }
    return target in transitions.get(current, [])

def can_transition_phase(current: Phase, target: Phase) -> bool:
    """
    Validate phase transitions (for VS mode).
    """
    transitions: dict[Phase, list[Phase]] = {
        "": ["DRAW"],
        "DRAW": ["GUESS"],
        "GUESS": ["DRAW", ""],  # "" means round end
    }
    return target in transitions.get(current, [])
