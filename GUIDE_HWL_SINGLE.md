# DrawGuess SINGLE Guide

Simple flow + developer terms for SINGLE mode.

---

## 1. SINGLE Flow (Simple)
1. Players connect and join.
2. Any player triggers `start_role_pick` once 3+ players are connected.
3. Server assigns GM, drawer, and guessers automatically.
4. GM sets round config (`set_round_config`).
5. GM starts game (`start_game`).
6. Phase `DRAW`: drawer sends `draw_op` (stroke limit enforced).
7. Guessers can send guesses during `DRAW` or `GUESS`.
8. If correct guess -> round ends -> `VOTING`.
9. If time expires -> round ends -> `VOTING`.
10. Entering `VOTING` clears roles for everyone.
11. All active players vote. YES -> `ROLE_PICK`. NO/tie -> stay `ROUND_END`.

---

## 2. SINGLE Developer Terms

**Drawer**
- Only player allowed to draw.

**Guesser**
- Players who can submit guesses.

**Stroke Limit**
- Max strokes per round for drawer.

**Round Config**
- Secret word, stroke limit, time limit (set by GM).

**Phase**
- `DRAW` -> `GUESS` -> `VOTING`.
