from __future__ import annotations

from app.domain.vs.handlers_config import handle_vs_set_round_config
from app.domain.vs.handlers_start_round import handle_vs_start_game
from app.domain.vs.handlers_draw import handle_vs_draw_op
from app.domain.vs.handlers_guess import handle_vs_guess
from app.domain.vs.handlers_phase import handle_vs_phase_tick
from app.domain.vs.handlers_sabotage import handle_vs_sabotage
from app.domain.vs.handlers_vote import handle_vs_vote_next
from app.domain.vs.handlers_role_pick import handle_vs_role_pick

__all__ = [
    "handle_vs_set_round_config",
    "handle_vs_start_game",
    "handle_vs_draw_op",
    "handle_vs_guess",
    "handle_vs_phase_tick",
    "handle_vs_sabotage",
    "handle_vs_vote_next",
    "handle_vs_role_pick",
]
