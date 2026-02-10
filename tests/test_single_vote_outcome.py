import pytest

from app.domain.single.handlers_vote import handle_single_vote_next
from app.store.models import PlayerStore, RoomHeaderStore


class FakeRepo:
    def __init__(self):
        self.header = RoomHeaderStore(
            mode="SINGLE",
            state="ROUND_END",
            cap=8,
            created_at=0,
            last_activity=0,
            gm_pid="gm",
            round_no=1,
        )
        self.players = {
            "gm": PlayerStore(pid="gm", name="GM", joined_at=0, last_seen=0, role="gm", connected=True),
            "g": PlayerStore(pid="g", name="Guesser", joined_at=0, last_seen=0, role="guesser", connected=True),
        }
        self.roles = {"gm": "gm", "drawer": "d"}
        self.round_cfg = {"secret_word": "apple"}
        self.game = {"phase": "VOTING", "votes_next": {}}
        self.active = {"gm", "g"}

    async def get_room_header(self, room_code):
        return self.header


    async def set_game_fields(self, room_code, **fields):
        self.game.update(fields)

    async def update_room_fields(self, room_code, **fields):
        for k, v in fields.items():
            setattr(self.header, k, v)

    async def refresh_room_ttl(self, room_code, mode):
        return None

    async def get_active_pids(self, room_code):
        return set(self.active)

    async def vote_next_clear(self, room_code):
        return None

    async def vote_next_add(self, room_code, pid):
        return 1

    async def list_players(self, room_code):
        return list(self.players.values())

    async def update_player_fields(self, room_code, pid, **fields):
        p = self.players[pid]
        for k, v in fields.items():
            setattr(p, k, v)

    async def set_roles(self, room_code, roles):
        self.roles = roles

    async def clear_ops(self, room_code, mode):
        return None

    async def get_roles(self, room_code):
        return dict(self.roles)

    async def get_round_config(self, room_code):
        return dict(self.round_cfg)

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
async def test_single_vote_yes_moves_to_role_pick():
    repo = FakeRepo()
    app = FakeApp(repo)

    class Msg:
        vote = "yes"

    await handle_single_vote_next(app=app, room_code="R1", pid="gm", msg=Msg())
    await handle_single_vote_next(app=app, room_code="R1", pid="g", msg=Msg())
    assert repo.header.state == "ROLE_PICK"


@pytest.mark.asyncio
async def test_single_vote_no_stays_round_end():
    repo = FakeRepo()
    app = FakeApp(repo)

    class Msg:
        vote = "no"

    await handle_single_vote_next(app=app, room_code="R1", pid="gm", msg=Msg())
    await handle_single_vote_next(app=app, room_code="R1", pid="g", msg=Msg())
    assert repo.header.state == "ROUND_END"
