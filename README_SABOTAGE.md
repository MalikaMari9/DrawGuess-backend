# Sabotage Behavior README

This document describes the current sabotage behavior for VS mode across backend and frontend.

## Overview

Sabotage lets a drawer draw a `line` or `circle` directly on the opponent canvas.
It has strict server validation and a cooldown.

## Core Rules

1. Mode/state/phase requirements:
- Room must be `VS`
- Room state must be `IN_GAME`
- Phase must be `DRAW`

2. Role/team requirements:
- Only drawers can sabotage
- Player must belong to a team
- Target must be the opponent team (cannot sabotage own team)

3. Operation requirements:
- Sabotage op type must be `line` or `circle`
- Invalid op types are rejected

4. Timing requirements:
- Sabotage is blocked in the last `30` seconds of draw phase

5. Cost and cooldown:
- Sabotage cost is exactly `1` stroke
- Cooldown is `180` seconds

## Backend Enforcement

Backend authority is in:
- `app/domain/vs/handlers_sabotage.py`
- `app/domain/vs/rules.py`

Behavior:
- Validates all sabotage preconditions
- Calls Redis atomic sabotage function with `cost=1`
- Appends sabotage draw op to opponent canvas
- Broadcasts:
  - `op_broadcast` (on target canvas)
  - `sabotage_used` (with `cooldown_until`)
  - `budget_update`

Important constants (`app/domain/vs/rules.py`):
- `SABOTAGE_COOLDOWN_SEC = 180`
- `SABOTAGE_DISABLE_LAST_SEC = 30`
- `SABOTAGE_COST_STROKES = 1`

## Frontend Behavior

Frontend files:
- `DrawGuess-frontend/src/pages/BattleGame.jsx`
- `DrawGuess-frontend/src/pages/BattleGameRT.jsx`

State model:
1. `Available`:
- Drawer in DRAW phase
- Enough stroke budget
- Not in cooldown
- Not in last 30 seconds
- Brush is `line` or `circle`

2. `Armed`:
- User clicks sabotage button
- Next valid stroke is treated as sabotage

3. `Sent`:
- On sabotage send, UI immediately starts local cooldown (`now + 180s`)
- Button becomes unusable immediately (no wait for round-trip)

4. `Confirmed`:
- Server emits `sabotage_used`
- UI updates with authoritative `cooldown_until`

## Error/Block Cases

Common server responses:
- `BAD_PHASE` - not in DRAW
- `NOT_DRAWER` - not a drawer
- `INVALID_TARGET` - own team target
- `SABOTAGE_BLOCKED` - cooldown or last-30s block
- `INVALID_SABOTAGE_OP` - op not line/circle
- `INSUFFICIENT_BUDGET` - not enough strokes

## Message Flow (Success)

1. Client arms sabotage
2. Client draws line/circle
3. Client sends:
- `{ "type": "sabotage", "target": "A|B", "op": { ... } }`
4. Server validates and charges 1 stroke
5. Server emits:
- `op_broadcast` (target canvas)
- `sabotage_used` (cooldown timestamp)
- `budget_update`

## Practical Notes

- If draw window is `<= 30` seconds, sabotage is effectively blocked for the entire draw phase.
- Backend is authoritative; frontend checks are only UX guards.

