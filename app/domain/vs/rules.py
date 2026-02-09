# app/domain/vs/rules.py
from __future__ import annotations

from typing import Optional, Literal
from app.domain.common.types import Team
from app.util.timeutil import now_ts

# VS Mode Constants
MIN_PLAYERS_VS = 5
STROKES_PER_PHASE_MIN = 3
STROKES_PER_PHASE_MAX = 5
SABOTAGE_COOLDOWN_SEC = 180
SABOTAGE_DISABLE_LAST_SEC = 30
SABOTAGE_COST_STROKES = 1

# Auto-split limits for stroke enforcement
MAX_STROKE_DURATION_SEC = 10
MAX_STROKE_POINTS = 1000


def validate_vs_start_conditions(players: list, teams: dict[str, list[str]], gm_pid: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """
    Check if VS mode can start.
    Returns (can_start, error_message)
    
    Requirements:
    - At least 5 players total (including GM)
    - Each team has at least 2 players (excluding GM)
    - Each team has exactly 1 drawer
    - GM is not on any team
    """
    if len(players) < MIN_PLAYERS_VS:
        return False, f"VS mode requires at least {MIN_PLAYERS_VS} players"
    
    team_a = teams.get("A", [])
    team_b = teams.get("B", [])
    
    # Exclude GM from team counts
    if gm_pid:
        team_a = [pid for pid in team_a if pid != gm_pid]
        team_b = [pid for pid in team_b if pid != gm_pid]
    
    if len(team_a) < 2 or len(team_b) < 2:
        return False, "Each team needs at least 2 players (excluding GM)"
    
    # Check for drawers (must be exactly 1 per team)
    drawer_a_count = sum(1 for p in players if p.role == "drawerA" and p.pid in teams.get("A", []))
    drawer_b_count = sum(1 for p in players if p.role == "drawerB" and p.pid in teams.get("B", []))
    
    if drawer_a_count != 1:
        return False, "Team A must have exactly 1 drawer"
    
    if drawer_b_count != 1:
        return False, "Team B must have exactly 1 drawer"
    
    return True, None


def calculate_strokes_per_phase() -> int:
    """
    Calculate strokes per phase (3-5 strokes per phase as per spec).
    Can be made configurable per room/round in the future.
    """
    # Default: 4 strokes per phase (within 3-5 range)
    # Can be randomized or made configurable: random.randint(STROKES_PER_PHASE_MIN, STROKES_PER_PHASE_MAX)
    return 4


def can_sabotage(
    cooldown_until: int,
    round_start_ts: int,
    round_duration_sec: int,
    current_ts: Optional[int] = None
) -> tuple[bool, Optional[str]]:
    """
    Check if sabotage is allowed.
    Returns (allowed, error_message)
    """
    ts = current_ts or now_ts()
    
    # Check cooldown
    if ts < cooldown_until:
        remaining = cooldown_until - ts
        return False, f"Sabotage on cooldown for {remaining} seconds"
    
    # Check if in last 30 seconds
    elapsed = ts - round_start_ts
    if elapsed >= (round_duration_sec - SABOTAGE_DISABLE_LAST_SEC):
        return False, "Sabotage disabled in last 30 seconds of round"
    
    return True, None


def should_auto_split_stroke(
    points: list[dict],
    start_ts: int,
    current_ts: Optional[int] = None
) -> bool:
    """
    Determine if a stroke should be auto-split by server.
    """
    ts = current_ts or now_ts()
    
    # Check duration
    if (ts - start_ts) > MAX_STROKE_DURATION_SEC:
        return True
    
    # Check point count
    if len(points) > MAX_STROKE_POINTS:
        return True
    
    return False
