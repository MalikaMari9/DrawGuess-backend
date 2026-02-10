# 🎮 Distributed Drawing Guessing Game (Revised to Match Current Backend)

This document reflects the **current implementation** (VS mode only, auto role-pick, moderation, Redis TTL).  
Single mode is planned but not yet implemented.

---

## 1. System Overview

**Characteristics**
- Real-time, event-driven, server-authoritative
- LAN/Wi-Fi clients
- Ephemeral sessions stored in Redis with TTL
- WebSocket-only API (no REST gameplay routes)

**Network Model**
```
Browser Clients  <->  FastAPI WebSocket Server  <->  Redis (TTL state)
```

---

## 2. Implemented Game Mode

### VS Mode (Team Competitive)

**Roles**
- GameMaster (GM)
- Team A: Drawer + Guessers
- Team B: Drawer + Guessers

**Minimum Players**
- 5 connected players

**Phase Flow**
1. **DRAW**: Each team drawer has a limited stroke budget (3–5).
2. **GUESS**: Each team may submit **one guess** in the phase.
3. **VOTING**: If no correct guess, active players vote for next round.

Phases repeat until a correct guess or vote outcome ends the round.

**Role Pick**
- **GM is assigned during `start_role_pick`** (not necessarily the room creator).
- Roles are **auto-assigned**: drawers are selected per team, others become guessers.
- Room moves directly to `CONFIG`.
 - The initial role pick can be triggered by any connected player.

---

## 3. Drawing System

**Tools**
1. Line tool (freehand)
2. Circle tool (center + radius)

**Rules**
- Each stroke consumes budget.
- Server auto-splits or rejects long strokes (duration or point count).
- Budget enforced server-side.

---

## 4. Sabotage (VS)

**Rules**
- Only drawers can sabotage.
- Cooldown: 180 seconds.
- Cost: 1 stroke from own team.
- Draws one stroke on opponent canvas.
- Disabled in last 30 seconds of round.

---

## 5. Voting (End of Round)

**Eligibility**
- **All active players can vote**, including the GM.

**Rules**
- Vote is allowed only in `VOTING` phase.
- Majority of active players required to proceed.
- Votes from inactive players are ignored.

**Outcome**
- Majority YES: new GM assigned, roles cleared, room returns to `ROLE_PICK`.
- NO / tie: round ends (`ROUND_END`).

---

## 6. Moderation

GM actions:
- Warn: increments warning count
- Mute: blocks actions until timestamp
- Kick: disconnects and blocks future actions

Kicked players are disconnected immediately.

---

## 7. Redis State (Implemented Keys)

Room-scoped keys (TTL refreshed on activity):
- `room:<code>` (HASH) room header
- `room:<code>:players` (HASH pid -> JSON)
- `room:<code>:active` (SET)
- `room:<code>:roles` (HASH)
- `room:<code>:team:A` / `room:<code>:team:B` (SETs)
- `room:<code>:round:config` (HASH)
- `room:<code>:game` (HASH)
- `room:<code>:budget` (HASH)
- `room:<code>:cooldown` (HASH)
- `room:<code>:ops:A` / `room:<code>:ops:B` (LIST)
- `room:<code>:votes:next` (SET)
- `room:<code>:modlog` (LIST)

---

## 8. Not Yet Implemented

- Single Mode rules
- Final canvas-based frontend (current frontend is a tester UI)
- Public / internet matchmaking
