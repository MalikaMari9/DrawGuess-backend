# app/domain/common/types.py
from __future__ import annotations

from typing import Literal, Optional

Mode = Literal["SINGLE", "VS"]
Team = Literal["A", "B"]
RoomState = Literal["WAITING", "ROLE_PICK", "CONFIG", "IN_ROUND", "ROUND_END"]
Phase = Literal["", "DRAW", "GUESS", "VOTING"]

Role = Literal["gm", "drawer", "guesser", "drawerA", "drawerB", "guesserA", "guesserB"]
