# DrawGuess Project Guide (All Modes)

This guide explains the full project flow in simple terms, but with developer accuracy.

---

## 1. Big Picture
- Clients talk to the server using WebSockets only.
- Server validates every action and stores state in Redis.
- Redis data has TTL; it is refreshed on activity.

---

## 2. End-to-End Flow

### A. Connect
1. Client connects to `/ws/{room_code}`.
2. Server assigns a `pid` and sends `hello`.
3. Client sends `join` with a player name.
4. Server stores player and returns `room_snapshot`.

### B. Role Pick (Lobby)
1. Room starts in `WAITING`.
2. Any player can trigger `start_role_pick` when enough players are connected.
3. Server assigns GM and roles automatically.
4. Room moves forward:
   - VS -> `CONFIG`
   - SINGLE -> `ROLE_PICK` / `CONFIG` (GM config step)

### C. Start Round
1. GM provides round config (SINGLE) or calls `start_round` (VS: stroke count, round time limit, guess window).
2. Server writes config to Redis and sets `IN_ROUND`.
3. Phase becomes `DRAW`.

### D. Draw Phase
1. Drawer sends `draw_op` messages.
2. Server validates tool + stroke limits and budget.
3. Server stores ops and broadcasts `op_broadcast`.

### E. Guess Phase
1. SINGLE allows guesses during `DRAW` or `GUESS`; VS allows guesses only during `GUESS`.
2. Server checks correctness.
3. If correct -> round ends -> `VOTING`.
4. VS guess window can auto-expire back to `DRAW` until round time ends.

### F. Voting Phase
1. All roles are cleared when entering voting (everyone becomes a player).
2. All active players vote.
3. YES -> new roles -> `ROLE_PICK`.
4. NO/tie -> round ends -> `ROUND_END`.

---

## 3. Developer Terms (Quick Reference)

**Room**
- A game session identified by 6-char code.

**Player**
- A connected user with a stable `pid`.

**GM (GameMaster)**
- Special role with control permissions; assigned at role-pick.

**State**
- Room state: `WAITING`, `ROLE_PICK`, `CONFIG`, `IN_ROUND`, `ROUND_END`.

**Phase**
- Round phase: `DRAW`, `GUESS`, `VOTING`.

**Op (Draw Operation)**
- A single drawing action (`line` or `circle`).

**Budget**
- Stroke counts enforced server-side.

**Snapshot**
- Full state sync to a client (room, players, roles, config, game, ops).

**TTL**
- Redis expiration time for room data.
