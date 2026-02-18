import pytest
from pydantic import ValidationError

from app.transport.protocols import parse_incoming


def test_parse_incoming_create_room():
    msg = parse_incoming({"type": "create_room", "mode": "VS", "cap": 12})
    assert msg.type == "create_room"
    assert msg.mode == "VS"
    assert msg.cap == 12


def test_parse_incoming_set_vs_config_bounds():
    msg = parse_incoming(
        {
            "type": "set_vs_config",
            "secret_word": "elephant",
            "draw_window_sec": 60,
            "strokes_per_phase": 4,
            "guess_window_sec": 10,
            "max_rounds": 5,
        }
    )
    assert msg.type == "set_vs_config"

    with pytest.raises(ValidationError):
        parse_incoming(
            {
                "type": "set_vs_config",
                "secret_word": "elephant",
                "draw_window_sec": 5,
                "strokes_per_phase": 4,
                "guess_window_sec": 10,
                "max_rounds": 5,
            }
        )


def test_parse_incoming_single_config():
    msg = parse_incoming(
        {
            "type": "set_round_config",
            "secret_word": "apple",
            "stroke_limit": 12,
            "time_limit_sec": 240,
        }
    )
    assert msg.type == "set_round_config"


def test_parse_incoming_unknown_type():
    with pytest.raises(ValueError):
        parse_incoming({"type": "does_not_exist"})
