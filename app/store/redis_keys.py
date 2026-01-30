# app/store/redis_keys.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RK:
    """
    Redis Key builder for room-scoped keys.
    Matches your blueprint.
    """
    room_code: str

    # ---- Core ----
    def room(self) -> str:
        return f"room:{self.room_code}"  # HASH

    def players(self) -> str:
        return f"room:{self.room_code}:players"  # HASH pid -> JSON

    def active(self) -> str:
        return f"room:{self.room_code}:active"  # SET pid

    def connections(self) -> str:
        return f"room:{self.room_code}:connections"  # SET conn_id or pid:conn

    def roles(self) -> str:
        return f"room:{self.room_code}:roles"  # HASH role -> pid

    # ---- Teams (VS) ----
    def team(self, team: str) -> str:
        # team should be "A" or "B"
        return f"room:{self.room_code}:team:{team}"  # SET pid

    def teams_meta(self) -> str:
        # optional, for storing team names/colors etc.
        return f"room:{self.room_code}:teams"  # HASH optional

    # ---- Round + live game ----
    def round_config(self) -> str:
        return f"room:{self.room_code}:round:config"  # HASH

    def game(self) -> str:
        return f"room:{self.room_code}:game"  # HASH live state

    # ---- Budgets / cooldown / ratelimit ----
    def budget(self) -> str:
        return f"room:{self.room_code}:budget"  # HASH (single: stroke_remaining, vs: team budgets)

    def cooldown(self) -> str:
        return f"room:{self.room_code}:cooldown"  # HASH e.g. sabotage_next_ts_A/B

    def ratelimit(self) -> str:
        return f"room:{self.room_code}:ratelimit"  # HASH or per pid keys

    # ---- Drawing ops ----
    def ops(self) -> str:
        return f"room:{self.room_code}:ops"  # LIST (single)

    def ops_team(self, team: str) -> str:
        return f"room:{self.room_code}:ops:{team}"  # LIST (vs A/B)

    # ---- Voting ----
    def votes_next(self) -> str:
        return f"room:{self.room_code}:votes:next"  # SET pid

    # ---- Moderation ----
    def modlog(self) -> str:
        return f"room:{self.room_code}:modlog"  # LIST entries JSON

    # ---- Convenience: all keys to TTL-refresh ----
    def all_room_keys(self, mode: str | None = None) -> list[str]:
        """
        Returns all keys that should share the same TTL policy.
        mode: "SINGLE" | "VS" | None
        """
        keys = [
            self.room(),
            self.players(),
            self.active(),
            self.connections(),
            self.roles(),
            self.round_config(),
            self.game(),
            self.budget(),
            self.cooldown(),
            self.ratelimit(),
            self.votes_next(),
            self.modlog(),
        ]
        if mode == "VS":
            keys.extend([self.team("A"), self.team("B"), self.ops_team("A"), self.ops_team("B"), self.teams_meta()])
        else:
            keys.append(self.ops())
        return keys
