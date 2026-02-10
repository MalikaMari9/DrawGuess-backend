# app/domain/single/handlers.py
from __future__ import annotations

from app.domain.single.handlers_config import handle_single_set_round_config
from app.domain.single.handlers_start import handle_single_start_game
from app.domain.single.handlers_draw import handle_single_draw_op
from app.domain.single.handlers_guess import handle_single_guess
from app.domain.single.handlers_phase import handle_single_phase_tick
from app.domain.single.handlers_vote import handle_single_vote_next

__all__ = [
    "handle_single_set_round_config",
    "handle_single_start_game",
    "handle_single_draw_op",
    "handle_single_guess",
    "handle_single_phase_tick",
    "handle_single_vote_next",
]
