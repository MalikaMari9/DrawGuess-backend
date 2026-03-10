
from dataclasses import dataclass

from app.domain.vs.rules import (
    validate_vs_start_conditions,
    should_auto_split_stroke,
)


@dataclass
class DummyPlayer:
    pid: str
    role: str | None = None


def _players_with_roles():
    return [
        DummyPlayer("p1", "drawerA"),
        DummyPlayer("p2", "guesserA"),
        DummyPlayer("p3", "drawerB"),
        DummyPlayer("p4", "guesserB"),
        DummyPlayer("gm", None),
    ]


def test_validate_vs_start_conditions_ok():
    players = _players_with_roles()
    teams = {"A": ["p1", "p2"], "B": ["p3", "p4"]}
    ok, err = validate_vs_start_conditions(players, teams, gm_pid="gm")
    assert ok is True
    assert err is None


def test_validate_vs_start_conditions_not_enough_players():
    players = [DummyPlayer("p1"), DummyPlayer("p2"), DummyPlayer("p3"), DummyPlayer("p4")]
    teams = {"A": ["p1", "p2"], "B": ["p3", "p4"]}
    ok, err = validate_vs_start_conditions(players, teams, gm_pid=None)
    assert ok is False
    assert "at least" in err


def test_validate_vs_start_conditions_missing_drawers():
    players = [
        DummyPlayer("p1", "guesserA"),
        DummyPlayer("p2", "guesserA"),
        DummyPlayer("p3", "guesserB"),
        DummyPlayer("p4", "guesserB"),
        DummyPlayer("gm", None),
    ]
    teams = {"A": ["p1", "p2"], "B": ["p3", "p4"]}
    ok, err = validate_vs_start_conditions(players, teams, gm_pid="gm")
    assert ok is False
    assert "drawer" in err


def test_should_auto_split_stroke_by_points():
    points = [{"x": 0, "y": 0}] * 1001
    assert should_auto_split_stroke(points, start_ts=0, current_ts=1) is True


def test_should_auto_split_stroke_by_duration():
    points = [{"x": 0, "y": 0}] * 2
    assert should_auto_split_stroke(points, start_ts=0, current_ts=9999) is True
