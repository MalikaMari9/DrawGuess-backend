# DrawGuess VS Guide (Team Mode)

Simple flow + developer terms for VS mode.

---

## 1. VS Flow (Simple)
1. Players connect and join.
2. Any player triggers `start_role_pick` once 5+ players are connected.
3. Server assigns GM and auto-splits teams A/B (GM excluded).
4. Roles auto-assigned (drawerA/drawerB; others guessers).
5. Room moves to `CONFIG`.
6. GM sets VS config with `set_vs_config` (secret_word, draw_window_sec, guess_window_sec, strokes_per_phase, max_rounds).
7. GM starts game with `start_game`.
8. Phase `DRAW`: drawers send `draw_op` (budget enforced) during draw window.
9. When draw window ends, phase switches to `GUESS` for both teams.
10. Each team gets one guess per round (any guesser). Wrong guess waits for other team or timer.
11. Correct guess -> game ends -> `GAME_END` + `VOTING`.
12. If no correct guess, guess window ends -> NO_GUESS for missing teams, advance to next round if round_no < max_rounds (same secret, canvas persists).
13. If max_rounds reached -> `GAME_END` (NO_WINNER) + `VOTING`.

---

## 2. VS Developer Terms

**Team A / Team B**
- Stored as Redis sets.

**Drawer / Guesser**
- One drawer per team, others guess.

**Sabotage**
- Drawer-only action that draws on opponent canvas.
- Costs 1 stroke, cooldown enforced, disabled in last 30s of draw window.

**Budget**
- Per-team stroke budget per DRAW window.

**Phase Loop**
- `DRAW` -> `GUESS` -> `DRAW` until game ends.
