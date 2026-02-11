# DrawGuess Backend (FastAPI + WebSocket + Redis)

This backend is **event-driven** and uses **WebSockets** as the main API.  
We do **NOT** build normal REST routes like `/rooms`, `/join`, etc.  
Instead, clients open one WebSocket connection and send JSON messages (events).  
The server is **authoritative**: it validates actions, updates Redis, and broadcasts events to players.

---

## Why WebSockets (not REST routes)"
This game needs real-time behavior:
- drawing strokes streamed live
- join/leave updates instantly
- round state / role changes broadcasted to everyone

REST endpoints are not ideal for this.  
So our "API" is a **WebSocket message protocol**.

---

## Folder Architecture (3 Layers)

### 1) `app/transport/` — WebSocket Transport Layer (NO game rules)
**Responsibilities**
- Accept WS connections: `/ws/{room_code}`
- Parse incoming JSON
- Dispatch messages to the domain layer
- Send outgoing events (unicast / broadcast)

**What NOT to do here**
- No room rules
- No scoring rules
- No direct Redis commands

Key files:
- `ws.py` → WS endpoint
- `ws_manager.py` → connection tracking + broadcast helpers
- `dispatcher.py` → routes message types to correct domain handler
- `protocols.py` → message/event schemas

---

### 2) `app/domain/` — Game Domain Layer (ALL game rules live here)
This is the **game engine**.  
It decides whether an action is allowed and what events to emit.

Modules:
- `domain/lifecycle/` → create/join/leave/reconnect/snapshot/heartbeat
- `domain/lobby/` → WAITING state: teams (VS), start conditions, etc.
- `domain/single/` → SINGLE mode rules (GM, drawer, guessers, budgets, rounds)
- `domain/vs/` → VS mode rules (two teams, two drawers, phases, sabotage)

Common shared utilities:
- `domain/common/fsm.py` → RoomState / Phase transitions
- `domain/common/validation.py` → guard checks (state guards, role guards)
- `domain/common/events.py` → event objects (to_sender / to_room)

**Where to implement features**
- SINGLE features → `domain/single/handlers.py` (+ `rules.py` if needed)
- VS features → `domain/vs/handlers.py` (+ `rules.py` / `sabotage.py` if needed)
- Lobby team selection → `domain/lobby/handlers.py`
- Join/leave snapshots → `domain/lifecycle/handlers.py`

---

### 3) `app/store/` — Redis Store Layer (NO game rules)
Redis is our "truth store" for room state (ephemeral, TTL-based).

**Responsibilities**
- Implement Redis keys (key naming)
- Read/write room + players + roles + game state
- Provide atomic operations if needed (budget consume, cooldown checks)

Key files:
- `redis_keys.py` → key builders (`room:<code>`, `room:<code>:players`, etc.)
- `redis_repo.py` → clean methods used by domain (e.g. `create_room()`, `add_player()`, `append_op()`)
- `models.py` → stored JSON models/schemas

**What NOT to do here**
- No "if player is GM then…" rules
- No scoring
- No state transitions
Those live in `domain/`.

---

## Redis Blueprint Reference
All Redis keys + data shapes are defined in:
- `app/store/redis_keys.py`
- `app/store/redis_repo.py`

If you need to store new room state, add it there (not random keys in domain/transport).

---

## Message Protocol (high-level)
Client → server JSON examples:
- `{"type":"create_room","mode":"SINGLE","cap":8}`
- `{"type":"join","name":"Malika"}`
- `{"type":"snapshot"}`

Server → client JSON examples:
- `{"type":"room_created","room_code":"AB12CD","mode":"SINGLE"}`
- `{"type":"room_snapshot", ... }`
- `{"type":"player_joined", ... }`
- `{"type":"error","code":"ROOM_NOT_FOUND","message":"..."}`

(Exact schemas are defined in `app/transport/protocols.py`.)

---

## Dev Setup (LAN friendly)

### Redis
```bash
docker start dp-redis
# if not created:
docker run --name dp-redis -p 6379:6379 -d redis:alpine
```
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

