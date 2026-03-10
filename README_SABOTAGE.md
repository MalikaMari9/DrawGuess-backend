# Sabotage Behavior (Current Runtime)

This document describes the active VS sabotage flow used by the live handlers.

## Overview

Sabotage lets a drawer apply one `line` or `circle` on the opponent canvas after arming sabotage.

## Core Rules

1. Room/phase gates:
- Room mode must be `VS`
- Room state must be `IN_GAME`
- Phase must be `DRAW`
- Draw window must still be open

2. Role/team gates:
- Only drawers can sabotage
- Drawer must belong to a team
- Target must be the opponent team (cannot sabotage own canvas)

3. Arm-first flow:
- Drawer sends `sabotage_arm`
- Next valid sabotage op can be sent with `sabotage`
- Armed state expires automatically after a short timeout or can be cancelled

4. Op validation:
- Only `line` and `circle` sabotage ops are accepted

5. Cost and usage limit:
- Costs exactly `1` stroke from the attacking team budget
- Limited to **once per team per game** (`sabotage_used`)

6. Not enforced:
- No cooldown gate
- No "disabled in last 30 seconds" gate

## Backend Authority

Runtime enforcement:
- `app/domain/vs/handlers_sabotage.py`
- Routed via `app/transport/dispatcher.py`

Notes:
- `app/domain/vs/rules.py` does not gate runtime sabotage calls.
- `OutSabotageUsed.cooldown_until` is emitted as `0` for compatibility with older payload shape.

## Frontend

Active VS page:
- `DrawGuessFrontend/src/pages/BattleGame.jsx`

Legacy page (not routed by default):
- `DrawGuessFrontend/src/pages/BattleGameRT.jsx`

## Common Error Codes

- `BAD_PHASE` - not in DRAW
- `DRAW_EXPIRED` - draw window ended
- `NOT_DRAWER` - only drawers may sabotage
- `NO_TEAM` - drawer has no team
- `INVALID_TARGET` - own-team target
- `SABOTAGE_BUSY` - another sabotage is currently armed
- `SABOTAGE_NOT_ARMED` - sabotage sent without valid arm state
- `SABOTAGE_USED` - team already used sabotage this game
- `INVALID_SABOTAGE_OP` - op type not line/circle
- `INVALID_SABOTAGE` - malformed line/circle payload
- `INSUFFICIENT_BUDGET` - not enough strokes

## Message Flow (Success)

1. Drawer sends `{ "type": "sabotage_arm" }`
2. Drawer draws a valid line/circle and sends `{ "type": "sabotage", "target": "A|B", "op": { ... } }`
3. Server validates, consumes 1 stroke, records team as used, and broadcasts:
- `op_broadcast` (target canvas)
- `sabotage_used` (`cooldown_until: 0`)
- `budget_update`
- `sabotage_state` inactive (`reason: "USED"`)

