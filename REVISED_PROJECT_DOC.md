# Distributed Drawing Guessing Game (Revised to Match Current Backend)

This document reflects the **current implementation** (VS + Single mode, auto role-pick, moderation, Redis TTL).

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

For detailed flow and roles, see:
- `GUIDE_ALL.md`
- `GUIDE_SLO_VS.md`
- `GUIDE_HWL_SINGLE.md`


---

## 2. Implemented Game Modes

### VS Mode (Team Competitive)

**Roles**
- GameMaster (GM)
- Team A: Drawer + Guessers
- Team B: Drawer + Guessers

**Minimum Players**
- 5 connected players

**Phase Flow**
1. **DRAW**: Each team drawer has a limited stroke budget (3-5).
2. **GUESS**: Each team may submit **one guess** in the phase.
3. If no correct guess, return to **DRAW** and reset stroke budgets.

Phases repeat until a correct guess or round time limit ends the round.

**Role Pick**
- **GM is assigned during `start_role_pick`** (not necessarily the room creator).
- Roles are **auto-assigned**: drawers are selected per team, others become guessers.
- Room moves directly to `CONFIG`.
- The initial role pick can be triggered by any connected player.
- VS teams are auto-assigned (balanced split); manual team selection is disabled.

### Single Mode (One Drawer, Many Guessers)

**Roles**
- GameMaster (GM)
- Drawer
- Guessers

**Minimum Players**
- 3 connected players

**Phase Flow**
1. **DRAW**: Drawer uses limited strokes (guessers may still guess).
2. **GUESS**: Guessers submit guesses (optional phase if you separate inputs).
3. **VOTING**: All active players vote to proceed.

Correct guess or time expiry ends the round and enters `VOTING`.

**Role Pick**
- GM assigned during `start_role_pick`.
- Drawer + guessers are auto-assigned.
- New rounds re-run role pick.

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
- Roles are cleared for everyone when entering `VOTING`.
- Majority of active players required to proceed.
- Votes from inactive players are ignored.

**Outcome**
- Majority YES: room returns to `ROLE_PICK` (new roles assigned).
- NO / tie: round ends (`GAME_END`).

---

## 6. Moderation

GM actions:
- Warn: increments warning count
- Mute: blocks actions until timestamp
- Kick: disconnects and blocks future actions

Kicked players are disconnected immediately.

---

## 7. Reconnect Behavior

- Clients receive a server-assigned `pid` on connect.
- On refresh, clients can send `reconnect` with the previous `pid`.
- Server restores the player's connection and returns a snapshot.
- If the room expired or pid is invalid, reconnect fails with an error.

---

## 8. Redis State (Implemented Keys)

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
- `room:<code>:ops` (LIST) for Single mode
- `room:<code>:votes:next` (SET)
- `room:<code>:modlog` (LIST)

---

## 9. Not Yet Implemented

- Final canvas-based frontend (current frontend is a tester UI)
- Public / internet matchmaking
