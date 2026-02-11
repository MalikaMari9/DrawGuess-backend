import pytest

from app.domain.common.end_round import handle_end_round
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
            "p1": PlayerStore(pid="p1", name="P1", joined_at=0, last_seen=0, role="guesser", connected=True),
        }
        self.roles = {"gm": "gm", "drawer": "p1"}
        self.round_cfg = {"secret_word": "Apple"}
        self.game = {"phase": "DRAW"}

    async def get_room_header(self, room_code):
        return self.header

    async def get_player(self, room_code, pid):
        return self.players.get(pid)

    async def list_players(self, room_code):
        return list(self.players.values())

    async def update_player_fields(self, room_code, pid, **fields):
        p = self.players[pid]
        for k, v in fields.items():
            setattr(p, k, v)

    async def set_roles(self, room_code, roles):
        self.roles = roles

    async def vote_next_clear(self, room_code):
        return None

    async def set_game_fields(self, room_code, **fields):
        self.game.update(fields)

    async def update_room_fields(self, room_code, **fields):
        for k, v in fields.items():
            setattr(self.header, k, v)

    async def refresh_room_ttl(self, room_code, mode):
        return None

    async def get_round_config(self, room_code):
        return dict(self.round_cfg)


class FakeApp:
    def __init__(self, repo):
        self.state = type("State", (), {"repo": repo})()


@pytest.mark.asyncio
async def test_gm_end_round_clears_roles_and_moves_to_voting():
    repo = FakeRepo()
    app = FakeApp(repo)

    class Msg:
        pass

    to_sender, to_room = await handle_end_round(app=app, room_code="R1", pid="gm", msg=Msg())
    assert repo.header.state == "ROUND_END"
    assert repo.game.get("phase") == "VOTING"
    assert repo.players["gm"].role is None
    assert repo.players["p1"].role is None
    assert any(getattr(e, "type", "") == "round_end" for e in to_room)
