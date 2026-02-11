import pytest

from app.store.redis_repo import RedisRepo


class GuardRepo(RedisRepo):
    def __init__(self):
        super().__init__(r=None)
        self.cleared = False
        self.cleared_args = None

    async def clear_team(self, room_code: str, pid: str) -> None:
        self.cleared = True
        self.cleared_args = (room_code, pid)


@pytest.mark.asyncio
async def test_set_team_guard_prevents_gm_assignment():
    repo = GuardRepo()
    await repo.set_team("R1", "gm", "A", gm_pid="gm")
    assert repo.cleared is True
    assert repo.cleared_args == ("R1", "gm")
