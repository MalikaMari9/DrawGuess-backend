# VS Mode Testing Guide (Windows / PowerShell)

This guide is tailored for a Windows machine using PowerShell with:
- Backend repo: `D:\DrawGuess-backend-main`
- Frontend repo: `D:\DrawGuess-frontend-main`

Adjust paths if your folders differ.

## Prerequisites

1. Backend server (FastAPI)
```bash
cd D:\DrawGuess-backend-main
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

2. Frontend server (Vite)
```bash
cd D:\DrawGuess-frontend-main
npm run dev
```
Frontend URL: `http://localhost:5173`

3. Redis running
```bash
# If using Docker
docker start dp-redis

# Or start Redis from your Windows service/installer
```

## Step-by-Step Testing (VS Mode)

### Step 1: Create VS Room 

1. Open `http://localhost:5173`
2. Enter a name (example: `Player1`)
3. Select mode: `VS`
4. Set capacity (example: `12`)
5. Click `Create Room`

Expected:
- Room code displayed
- Status: CONNECTED
- Room state: WAITING

---

### Step 2: Join with Additional Players (Players 2-5)

For each additional player (minimum 5 total):
1. Open a new browser window or incognito
2. Go to `http://localhost:5173`
3. Enter a different name (example: `Player2`, `Player3`)
4. Enter the room code
5. Click `Join Room`

Expected:
- Each player joins successfully
- Lobby shows all players
- Room state remains WAITING

---

### Step 3: Team Selection (WAITING)

Each player (except GM):
1. In the lobby, open `Team Selection`
2. Click `Join Team A` or `Join Team B`

Expected:
- Teams show members correctly
- GM sees both teams filling

Tip:
- Team A: 2-3 players
- Team B: 2-3 players

---

### Step 4: Start Role Pick (GM Assigned Here, Auto-Assign)

1. Confirm 5+ players and both teams have members
2. Click `Start Role Pick`

Expected:
- GM is assigned automatically if none exists
- Roles are auto-assigned (drawerA/drawerB; others guessers)
- State changes to CONFIG
- Roles visible to each player

---

### Step 5: Start Round (GM Only)

1. In CONFIG state, open `Start Round`
2. Enter a word (example: `elephant`)
3. Click `Start Round`

Expected:
- State: IN_ROUND
- Phase: DRAW
- Canvases visible
- Budget shown (example: A: 4, B: 4)

---

### Step 6: Test Drawing (Drawers Only)

1. In DRAW phase, use `Test Draw (Line)`
2. Send multiple strokes until budget is 0

Expected:
- Ops broadcast to all players
- Budget decrements per stroke
- Drawing blocked at 0

---

### Step 7: Test Sabotage (Drawers Only)

1. In DRAW phase, click `Sabotage Opponent`

Expected:
- Op appears on opponent canvas
- Your budget decreases by 1
- Cooldown starts (180 seconds)
- Disabled in last 30 seconds

Test cooldown:
- Try again immediately -> cooldown error
- Wait 180 seconds -> works again

---

### Step 8: Advance to GUESS (GM Only)

1. Click `Advance Phase (DRAW <-> GUESS)`

Expected:
- Phase changes to GUESS
- Budget resets for next DRAW
- Drawers cannot draw

---

### Step 9: Test Guessing (Guessers Only)

1. Enter a guess and submit

Expected:
- Incorrect guess -> result shown, no second guess this phase
- Correct guess -> round ends, winner announced, state ROUND_END

---

### Step 10: Phase Cycling (GM Only)

1. If no correct guess, click `Advance Phase` again

Expected:
- Phase cycles DRAW -> GUESS -> DRAW
- Budget resets each DRAW

---

### Step 11: Round End

When a team guesses correctly:
- Round ends automatically
- State: ROUND_END
- Winner and word revealed

---

## Testing Checklist

### Checklist: Basic Flow
- [ ] Create VS room
- [ ] Join with 5+ players
- [ ] Assign teams
- [ ] Roles auto-assigned on role pick
- [ ] Start round
- [ ] Draw operations work
- [ ] Guess operations work
- [ ] Phase transitions work
- [ ] Round ends on correct guess

### Checklist: Drawing System
- [ ] Line tool works
- [ ] Circle tool works (if implemented)
- [ ] Stroke budget enforced
- [ ] Budget decreases correctly
- [ ] No drawing when budget = 0
- [ ] Auto-split prevents long strokes

### Checklist: Sabotage
- [ ] Only drawers can sabotage
- [ ] Costs 1 stroke from own team
- [ ] 180s cooldown works
- [ ] Disabled in last 30 seconds
- [ ] Cannot sabotage own team

### Checklist: Game Rules
- [ ] Minimum 5 players enforced
- [ ] Each team needs a drawer
- [ ] One guess per team per phase
- [ ] Correct guess ends round
- [ ] Phase cycling works

### Checklist: UI/UX
- [ ] Teams displayed correctly
- [ ] Roles shown correctly
- [ ] Budget updates in real-time
- [ ] Phase displayed correctly
- [ ] GM controls only for GM
- [ ] Drawer controls only for drawers
- [ ] Guesser controls only for guessers

---

## Common Issues

### "VS mode requires at least 5 players"
Fix: Make sure 5+ players are in the room before role pick.

### "Only GameMaster can start role pick"
Fix: Role pick assigns the GM; any connected player can trigger the initial role pick. Later GM-only actions still require the assigned GM.

### "No strokes remaining"
Fix: Budget is consumed. Wait for next DRAW phase.

### "Sabotage on cooldown"
Fix: Wait 180 seconds between sabotages.

### "Not in DRAW phase"
Fix: GM must advance to DRAW.

### "Already guessed"
Fix: One guess per team per GUESS phase.

---

## Debugging Tips

1. Check browser console (F12) for WebSocket errors
2. Check backend logs for event flow
3. Use Snapshot button to refresh state
4. Inspect Event Log for message order
5. Expand Debug: Full Snapshot to verify room data

---

## Expected Message Flow (Examples)

### Creating Room
```
Client -> {type: "create_room", mode: "VS", cap: 12}
Server -> {type: "room_created", room_code: "ABC123", mode: "VS"}
```

### Joining
```
Client -> {type: "join", name: "Player1"}
Server -> {type: "room_snapshot", ...}
Server -> {type: "player_joined", pid: "...", name: "Player1"}
```

### Team Selection
```
Client -> {type: "set_team", team: "A"}
Server -> {type: "teams_updated", teams: {"A": [...], "B": [...]}}
```

### Starting Round
```
Client -> {type: "start_round", word: "elephant"}
Server -> {type: "room_state_changed", state: "IN_ROUND"}
Server -> {type: "phase_changed", phase: "DRAW", round_no: 1}
Server -> {type: "budget_update", budget: {"A": 4, "B": 4}}
```

### Drawing
```
Client -> {type: "draw_op", canvas: "A", op: {...}}
Server -> {type: "op_broadcast", canvas: "A", op: {...}, by: "..."}
Server -> {type: "budget_update", budget: {"A": 3, "B": 4}}
```

### Guessing
```
Client -> {type: "guess", text: "elephant"}
Server -> {type: "guess_result", correct: true, team: "A", ...}
Server -> {type: "round_end", winner: "A", word: "elephant", ...}
```
