from app.domain.common.validation import (
    is_gm,
    is_drawer,
    is_guesser,
    is_muted,
    is_kicked,
)
from app.store.models import PlayerStore, RoomHeaderStore


def test_is_gm():
    header = RoomHeaderStore(mode="VS", created_at=0, last_activity=0, gm_pid="p1", round_no=0)
    player = PlayerStore(pid="p1", name="A", joined_at=0, last_seen=0)
    assert is_gm(player, header) is True


def test_is_drawer_team_specific():
    player = PlayerStore(pid="p1", name="A", joined_at=0, last_seen=0, role="drawerA", team="A")
    assert is_drawer(player) is True
    assert is_drawer(player, "A") is True
    assert is_drawer(player, "B") is False


def test_is_guesser_team_specific():
    player = PlayerStore(pid="p2", name="B", joined_at=0, last_seen=0, role="guesserB", team="B")
    assert is_guesser(player) is True
    assert is_guesser(player, "B") is True
    assert is_guesser(player, "A") is False


def test_is_muted_and_kicked():
    player = PlayerStore(pid="p3", name="C", joined_at=0, last_seen=0, muted_until=100, kicked=True)
    assert is_muted(player, 50) is True
    assert is_muted(player, 150) is False
    assert is_kicked(player) is True
