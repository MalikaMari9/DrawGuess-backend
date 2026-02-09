# app/domain/vs/handlers.py
from __future__ import annotations

from app.domain.vs.handlers_common import Result
from app.domain.vs.handlers_draw import handle_vs_draw_op
from app.domain.vs.handlers_guess import handle_vs_guess
from app.domain.vs.handlers_phase import handle_vs_phase_tick
from app.domain.vs.handlers_role_pick import handle_vs_role_pick
from app.domain.vs.handlers_sabotage import handle_vs_sabotage
from app.domain.vs.handlers_start_round import handle_vs_start_round
from app.domain.vs.handlers_vote import handle_vs_vote_next

__all__ = [
    "Result",
    "handle_vs_role_pick",
    "handle_vs_start_round",
    "handle_vs_draw_op",
    "handle_vs_guess",
    "handle_vs_vote_next",
    "handle_vs_phase_tick",
    "handle_vs_sabotage",
]