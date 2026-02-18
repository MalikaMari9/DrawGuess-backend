import pytest

from app.domain.single.handlers_config import handle_single_set_round_config
from app.domain.single.handlers_start import handle_single_start_game
from app.store.models import PlayerStore, RoomHeaderStore


class FakeRepo:
    def __init__(self):
        self.header = RoomHeaderStore(
            mode="SINGLE",
            state="ROLE_PICK",
            cap=8,
            created_at=0,
            last_activity=0,
            gm_pid="gm",
            round_no=0,
        )
        self.players = {
            "gm": PlayerStore(pid="gm", name="GM", joined_at=0, last_seen=0, role="gm", connected=True),
            "d": PlayerStore(pid="d", name="Drawer", joined_at=0, last_seen=0, role="drawer", connected=True),
        }
        self.roles = {"gm": "gm", "drawer": "d"}
        self.round_cfg = {}
        self.game = {}

    async def get_room_header(self, room_code):
        return self.header

    async def get_player(self, room_code, pid):
        return self.players.get(pid)

    async def get_round_config(self, room_code):
        return self.round_cfg

    async def set_round_config(self, room_code, cfg):
        self.round_cfg = dict(cfg)

    async def get_roles(self, room_code):
        return dict(self.roles)

    async def set_game_fields(self, room_code, **fields):
        self.game.update(fields)

    async def update_room_fields(self, room_code, **fields):
        for k, v in fields.items():
            setattr(self.header, k, v)

    async def refresh_room_ttl(self, room_code, mode):
        return None

    async def list_players(self, room_code):
        return list(self.players.values())

    async def get_roles(self, room_code):
        return dict(self.roles)

    async def get_game(self, room_code):
        return dict(self.game)

    async def get_ops_single(self, room_code):
        return []

    async def get_ops_vs(self, room_code, team):
        return []

    async def get_modlog(self, room_code):
        return []

    async def get_budget(self, room_code):
        return {}

    async def get_team_members(self, room_code, team):
        return set()


class FakeApp:
    def __init__(self, repo):
        self.state = type("State", (), {"repo": repo})()


@pytest.mark.asyncio
async def test_single_set_round_config_requires_gm():
    repo = FakeRepo()
    app = FakeApp(repo)

    class Msg:
        secret_word = "apple"
        stroke_limit = 12
        time_limit_sec = 240

    to_sender, _ = await handle_single_set_round_config(app=app, room_code="R1", pid="gm", msg=Msg())
    assert repo.round_cfg.get("secret_word") == "apple"
    assert any(getattr(e, "type", "") == "room_state_changed" for e in to_sender)


@pytest.mark.asyncio
async def test_single_start_game_requires_config():
    repo = FakeRepo()
    app = FakeApp(repo)

    class Msg:
        pass

    to_sender, _ = await handle_single_start_game(app=app, room_code="R1", pid="gm", msg=Msg())
    assert any(getattr(e, "type", "") == "error" for e in to_sender)

    repo.round_cfg = {"secret_word": "apple", "stroke_limit": 10, "time_limit_sec": 240}
    to_sender, to_room = await handle_single_start_game(app=app, room_code="R1", pid="gm", msg=Msg())
    assert repo.header.state == "IN_GAME"
    assert any(getattr(e, "type", "") == "phase_changed" for e in to_room)
