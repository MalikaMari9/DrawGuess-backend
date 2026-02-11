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


---

## 2. Project Flow (Simple, End-to-End)

This is the full flow from a player connecting to a round ending. It applies to BOTH modes unless noted.

### A. Connection and Identity
1. Client connects to WebSocket: `/ws/{room_code}`.
2. Server assigns a `pid` and sends `hello`.
3. Client sends `join` with a display name.
4. Server stores player in Redis and returns a `room_snapshot`.

### B. Lobby and Role Pick
1. Room starts in `WAITING`.
2. Any player can trigger `start_role_pick` when enough players are connected.
3. Server assigns GM and roles automatically.
4. Room moves to:
   - `CONFIG` for VS
   - `ROLE_PICK` or `CONFIG` for SINGLE (GM sets round config)

### C. Round Start
1. GM sends round config (SINGLE) or `start_round` (VS).
2. Server writes config to Redis and sets `IN_ROUND`.
3. Phase becomes `DRAW`.

### D. Drawing Phase
1. Drawer sends `draw_op` messages.
2. Server validates the op and budget.
3. Server stores the op and broadcasts `op_broadcast`.
4. When the phase ends, server moves to `GUESS`.

### E. Guess Phase
1. SINGLE allows guesses during `DRAW` or `GUESS`; VS allows guesses only during `GUESS`.
2. Server checks correctness.
3. If correct, round ends and phase moves to `VOTING`.
4. If VS guess window ends without a correct guess, server returns to `DRAW`.

### F. Voting Phase
1. Roles are cleared for everyone when entering `VOTING`.
2. All active players vote.
3. If YES wins, server returns to `ROLE_PICK` (new roles).
4. If NO wins or tie, round ends and room stays in `ROUND_END`.

---

## 3. Developer Terms (Quick Reference)

Use these terms consistently in code and docs.

**Room**
- A game session identified by a 6-char room code.
- Stored in Redis under `room:<code>`.

**Player**
- A connected user with a stable `pid`.
- Stored in `room:<code>:players`.

**GM (GameMaster)**
- Special role with control permissions.
- Assigned during role pick, not on room creation.

**State**
- Room-level state: `WAITING`, `ROLE_PICK`, `CONFIG`, `IN_ROUND`, `ROUND_END`.

**Phase**
- Round-level phase: `DRAW`, `GUESS`, `VOTING`.

**Op (Draw Operation)**
- A single drawing action (line or circle).
- Stored in Redis list and broadcast to clients.

**Budget**
- Stroke count available to drawers.
- Enforced server-side.

**Snapshot**
- Full state sync to a client (room, players, roles, config, game, ops).

**TTL**
- Redis expiration time for room data, refreshed on activity.


---

## 4. Implemented Game Modes

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

## 5. Drawing System

**Tools**
1. Line tool (freehand)
2. Circle tool (center + radius)

**Rules**
- Each stroke consumes budget.
- Server auto-splits or rejects long strokes (duration or point count).
- Budget enforced server-side.

---

## 6. Sabotage (VS)

**Rules**
- Only drawers can sabotage.
- Cooldown: 180 seconds.
- Cost: 1 stroke from own team.
- Draws one stroke on opponent canvas.
- Disabled in last 30 seconds of round.

---

## 7. Voting (End of Round)

**Eligibility**
- **All active players can vote**, including the GM.

**Rules**
- Vote is allowed only in `VOTING` phase.
- Roles are cleared for everyone when entering `VOTING`.
- Majority of active players required to proceed.
- Votes from inactive players are ignored.

**Outcome**
- Majority YES: room returns to `ROLE_PICK` (new roles assigned).
- NO / tie: round ends (`ROUND_END`).

---

## 8. Moderation

GM actions:
- Warn: increments warning count
- Mute: blocks actions until timestamp
- Kick: disconnects and blocks future actions

Kicked players are disconnected immediately.

---

## 9. Reconnect Behavior

- Clients receive a server-assigned `pid` on connect.
- On refresh, clients can send `reconnect` with the previous `pid`.
- Server restores the player’s connection and returns a snapshot.
- If the room expired or pid is invalid, reconnect fails with an error.

---

## 10. Redis State (Implemented Keys)

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

## 11. Not Yet Implemented

- Final canvas-based frontend (current frontend is a tester UI)
- Public / internet matchmaking
