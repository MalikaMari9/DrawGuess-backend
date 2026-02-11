# DrawGuess VS Guide (Team Mode)

Simple flow + developer terms for VS mode.

---

## 1. VS Flow (Simple)
1. Players connect and join.
2. Any player triggers `start_role_pick` once 5+ players are connected.
3. Server assigns GM and auto-splits teams A/B (GM excluded).
4. Room moves to `CONFIG`.
5. GM starts round with `start_round` (secret + round time limit + guess window + stroke budget).
6. Phase `DRAW`: drawers send `draw_op` (budget enforced).
7. Phase `GUESS`: each team submits one guess per phase.
8. If correct guess -> round ends.
9. If not correct -> move back to `DRAW` (new strokes).
10. Round ends only on correct guess or time limit.
11. After round end -> `VOTING` to decide next round (roles are cleared on entry).

---

## 2. VS Developer Terms

**Team A / Team B**
- Stored as Redis sets.

**Drawer / Guesser**
- One drawer per team, others guess.

**Sabotage**
- Drawer-only action that draws on opponent canvas.
- Costs 1 stroke, cooldown enforced, disabled in last 30s.

**Budget**
- Per-team stroke budget per DRAW phase.

**Phase Loop**
- `DRAW` -> `GUESS` -> `DRAW` until round ends.
