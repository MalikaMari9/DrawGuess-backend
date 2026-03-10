import copy

import pytest

from app.domain.vs.handlers_sabotage import handle_vs_sabotage, handle_vs_sabotage_arm
from app.store.models import PlayerStore, RoomHeaderStore
from app.util.timeutil import now_ts


class FakeRepo:
    def __init__(self):
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
            "draw_end_at": ts + 5,  # explicitly inside final seconds window
            "sabotage_used": {"A": False, "B": False},
            "sabotage_armed_by": "",
            "sabotage_armed_team": "",
            "sabotage_target_team": "",
            "sabotage_armed_until": 0,
        }
        self.budget = {"A": 3, "B": 3}
        self.ops = []

    async def get_room_header(self, room_code):
        return self.header

    async def get_game(self, room_code):
        return copy.deepcopy(self.game)

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


class ArmMsg:
    pass


class SabotageMsg:
    def __init__(self, target="B", op=None):
        self.target = target
        self.op = op or {
            "t": "line",
            "pts": [{"x": 0, "y": 0}, {"x": 10, "y": 10}],
            "color": "#ffffff",
            "size": 2,
        }


def _error_codes(events):
    return [getattr(e, "code", "") for e in events if getattr(e, "type", "") == "error"]


@pytest.mark.asyncio
async def test_vs_runtime_allows_sabotage_in_final_seconds_when_armed():
    repo = FakeRepo()
    app = FakeApp(repo)

    arm_sender, _ = await handle_vs_sabotage_arm(app=app, room_code="R1", pid="a_drawer", msg=ArmMsg())
    assert not _error_codes(arm_sender)

    to_sender, to_room = await handle_vs_sabotage(
        app=app,
        room_code="R1",
        pid="a_drawer",
        msg=SabotageMsg(target="B"),
    )
    assert not _error_codes(to_sender)

    room_types = {getattr(e, "type", "") for e in to_room}
    assert "op_broadcast" in room_types
    assert "sabotage_used" in room_types
    assert "budget_update" in room_types

    sabotage_used_ev = next(e for e in to_room if getattr(e, "type", "") == "sabotage_used")
    assert sabotage_used_ev.cooldown_until == 0
    assert repo.game["sabotage_used"]["A"] is True


@pytest.mark.asyncio
async def test_vs_runtime_sabotage_requires_armed_state():
    repo = FakeRepo()
    app = FakeApp(repo)

    to_sender, _ = await handle_vs_sabotage(
        app=app,
        room_code="R2",
        pid="a_drawer",
        msg=SabotageMsg(target="B"),
    )
    assert "SABOTAGE_NOT_ARMED" in _error_codes(to_sender)


@pytest.mark.asyncio
async def test_vs_runtime_blocks_second_sabotage_same_team():
    repo = FakeRepo()
    app = FakeApp(repo)

    arm_sender, _ = await handle_vs_sabotage_arm(app=app, room_code="R3", pid="a_drawer", msg=ArmMsg())
    assert not _error_codes(arm_sender)
    first_sender, _ = await handle_vs_sabotage(
        app=app,
        room_code="R3",
        pid="a_drawer",
        msg=SabotageMsg(target="B"),
    )
    assert not _error_codes(first_sender)

    budget_after_first = repo.budget["A"]
    second_arm_sender, _ = await handle_vs_sabotage_arm(app=app, room_code="R3", pid="a_drawer", msg=ArmMsg())
    assert "SABOTAGE_USED" in _error_codes(second_arm_sender)
    assert repo.budget["A"] == budget_after_first

