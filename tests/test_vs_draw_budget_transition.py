import copy

import pytest

from app.domain.vs.handlers_draw import handle_vs_draw_op
from app.domain.vs.handlers_sabotage import handle_vs_sabotage, handle_vs_sabotage_arm
from app.store.models import PlayerStore, RoomHeaderStore
from app.util.timeutil import now_ts


class FakeRepo:
    def __init__(self, *, budget_a: int, budget_b: int):
        ts = now_ts()
        self.header = RoomHeaderStore(
            mode="VS",
            state="IN_GAME",
            cap=8,
            created_at=ts,
            last_activity=ts,
            gm_pid="gm",
            round_no=1,
        )
        self.players = {
            "gm": PlayerStore(pid="gm", name="GM", joined_at=ts, last_seen=ts, role="gm", connected=True),
            "a_drawer": PlayerStore(
                pid="a_drawer",
                name="A Drawer",
                joined_at=ts,
                last_seen=ts,
                role="drawerA",
                team="A",
                connected=True,
            ),
            "b_drawer": PlayerStore(
                pid="b_drawer",
                name="B Drawer",
                joined_at=ts,
                last_seen=ts,
                role="drawerB",
                team="B",
                connected=True,
            ),
        }
        self.game = {
            "phase": "DRAW",
            "draw_end_at": ts + 120,
            "sabotage_used": {"A": False, "B": False},
            "sabotage_armed_by": "",
            "sabotage_armed_team": "",
            "sabotage_target_team": "",
            "sabotage_armed_until": 0,
            "transition_until": 0,
            "transition_next": "",
            "transition_front": "",
            "transition_back": "",
        }
        self.round_cfg = {"guess_window_sec": 10, "strokes_per_phase": 4, "draw_window_sec": 20}
        self.budget = {"A": budget_a, "B": budget_b}
        self.ops = []

    async def get_room_header(self, room_code):
        return self.header

    async def get_game(self, room_code):
        return copy.deepcopy(self.game)

    async def get_round_config(self, room_code):
        return dict(self.round_cfg)

    async def set_game_fields(self, room_code, **fields):
        self.game.update(fields)

    async def get_player(self, room_code, pid):
        return self.players.get(pid)

    async def update_room_fields(self, room_code, **fields):
        for k, v in fields.items():
            setattr(self.header, k, v)

    async def refresh_room_ttl(self, room_code, mode):
        return None

    async def consume_vs_stroke(self, room_code, team, cost=1):
        cur = int(self.budget.get(team, 0))
        if cur < cost:
            return False, cur
        self.budget[team] = cur - cost
        return True, self.budget[team]

    async def append_op_vs(self, room_code, team, op):
        self.ops.append((team, op))

    async def get_budget(self, room_code):
        return dict(self.budget)


class FakeApp:
    def __init__(self, repo):
        self.state = type("State", (), {"repo": repo})()


class DrawMsg:
    def __init__(self, *, canvas="A"):
        self.canvas = canvas
        self.op = {
            "t": "line",
            "pts": [[0, 0], [10, 10]],
            "c": "#ffffff",
            "w": 2,
        }


class ArmMsg:
    pass


class SabotageMsg:
    def __init__(self, target="B"):
        self.target = target
        self.op = {
            "t": "line",
            "pts": [[0, 0], [10, 10]],
            "color": "#ffffff",
            "size": 2,
        }


def _error_codes(events):
    return [getattr(e, "code", "") for e in events if getattr(e, "type", "") == "error"]


@pytest.mark.asyncio
async def test_vs_draw_transitions_to_guess_when_both_budgets_hit_zero():
    repo = FakeRepo(budget_a=1, budget_b=0)
    app = FakeApp(repo)

    to_sender, to_room = await handle_vs_draw_op(
        app=app,
        room_code="R1",
        pid="a_drawer",
        msg=DrawMsg(canvas="A"),
    )
    assert not _error_codes(to_sender)
    assert repo.budget["A"] == 0
    assert repo.budget["B"] == 0
    assert repo.game["phase"] == "TRANSITION"
    assert repo.game["transition_next"] == "GUESS"
    assert repo.game["transition_front"] == "OUT OF STROKES!"
    assert any(getattr(e, "type", "") == "phase_changed" for e in to_room)


@pytest.mark.asyncio
async def test_vs_sabotage_transitions_to_guess_when_both_budgets_hit_zero():
    repo = FakeRepo(budget_a=1, budget_b=0)
    app = FakeApp(repo)

    arm_sender, _ = await handle_vs_sabotage_arm(app=app, room_code="R2", pid="a_drawer", msg=ArmMsg())
    assert not _error_codes(arm_sender)

    to_sender, to_room = await handle_vs_sabotage(
        app=app,
        room_code="R2",
        pid="a_drawer",
        msg=SabotageMsg(target="B"),
    )
    assert not _error_codes(to_sender)
    assert repo.budget["A"] == 0
    assert repo.budget["B"] == 0
    assert repo.game["phase"] == "TRANSITION"
    assert repo.game["transition_next"] == "GUESS"
    assert repo.game["transition_front"] == "OUT OF STROKES!"
    assert any(getattr(e, "type", "") == "phase_changed" for e in to_room)
