import pytest

from app.domain.single.handlers_guess import handle_single_guess
from app.domain.single.handlers_phase import handle_single_phase_tick
from app.domain.single.handlers_vote import handle_single_vote_next
from app.store.models import PlayerStore, RoomHeaderStore


class FakeRepo:
    def __init__(self):
        self.header = RoomHeaderStore(
            mode="SINGLE",
            state="IN_ROUND",
            cap=8,
            created_at=0,
            last_activity=0,
            gm_pid="gm",
            round_no=1,
        )
        self.players = {
            "gm": PlayerStore(pid="gm", name="GM", joined_at=0, last_seen=0, role="gm", connected=True),
            "d": PlayerStore(pid="d", name="Drawer", joined_at=0, last_seen=0, role="drawer", connected=True),
            "g": PlayerStore(pid="g", name="Guesser", joined_at=0, last_seen=0, role="guesser", connected=True),
        }
        self.roles = {"gm": "gm", "drawer": "d"}
        self.round_cfg = {"secret_word": "Apple", "stroke_limit": 10, "time_limit_sec": 240}
        self.game = {"phase": "GUESS", "votes_next": {}}
        self.active = {"gm", "d", "g"}

    async def get_room_header(self, room_code):
        return self.header

    async def get_player(self, room_code, pid):
        return self.players.get(pid)

    async def get_round_config(self, room_code):
        return self.round_cfg

    async def get_game(self, room_code):
        return dict(self.game)

    async def set_game_fields(self, room_code, **fields):
        self.game.update(fields)

    async def update_room_fields(self, room_code, **fields):
        for k, v in fields.items():
            setattr(self.header, k, v)

    async def refresh_room_ttl(self, room_code, mode):
        return None

    async def vote_next_clear(self, room_code):
        return None

    async def set_round_config(self, room_code, cfg):
        self.round_cfg = dict(cfg)

    async def append_op_single(self, room_code, op):
        return None

    async def get_ops_single(self, room_code):
        return []

    async def get_modlog(self, room_code):
        return []

    async def get_roles(self, room_code):
        return dict(self.roles)

    async def get_budget(self, room_code):
        return {}

    async def get_team_members(self, room_code, team):
        return set()

    async def get_ops_vs(self, room_code, team):
        return []
    async def get_active_pids(self, room_code):
        return set(self.active)

    async def set_roles(self, room_code, roles):
        self.roles = roles

    async def list_players(self, room_code):
        return list(self.players.values())

    async def update_player_fields(self, room_code, pid, **fields):
        p = self.players[pid]
        for k, v in fields.items():
            setattr(p, k, v)

    async def clear_ops(self, room_code, mode):
        return None

    async def vote_next_add(self, room_code, pid):
        return 1

    async def vote_next_clear(self, room_code):
        return None


class FakeApp:
    def __init__(self, repo):
        self.state = type("State", (), {"repo": repo})()


@pytest.mark.asyncio
async def test_single_correct_guess_moves_to_voting():
    repo = FakeRepo()
    app = FakeApp(repo)

    class Msg:
        text = "apple"

    to_sender, to_room = await handle_single_guess(app=app, room_code="R1", pid="g", msg=Msg())
    assert repo.header.state == "ROUND_END"
    assert repo.game.get("phase") == "VOTING"
    # should emit phase change and round end
    types = {e.type for e in to_room if hasattr(e, "type")}
    assert "phase_changed" in types
    assert "round_end" in types


@pytest.mark.asyncio
async def test_single_phase_tick_gm_only():
    repo = FakeRepo()
    app = FakeApp(repo)

    class Msg:
        pass

    # GM can tick
    to_sender, to_room = await handle_single_phase_tick(app=app, room_code="R1", pid="gm", msg=Msg())
    assert any(getattr(e, "type", "") == "phase_changed" for e in to_room)

    # Non-GM blocked
    to_sender, to_room = await handle_single_phase_tick(app=app, room_code="R1", pid="g", msg=Msg())
    assert any(getattr(e, "type", "") == "error" for e in to_sender)


@pytest.mark.asyncio
async def test_single_vote_all_active():
    repo = FakeRepo()
    app = FakeApp(repo)
    repo.header.state = "ROUND_END"
    repo.game["phase"] = "VOTING"

    class Msg:
        vote = "yes"

    to_sender, to_room = await handle_single_vote_next(app=app, room_code="R1", pid="gm", msg=Msg())
    # vote is accepted from GM (active)
    assert not any(getattr(e, "type", "") == "error" for e in to_sender)
