from app.domain.common.ops import validate_draw_op


def test_validate_draw_op_line_ok():
    ok, op_type, err_code, err_msg = validate_draw_op({"t": "line", "pts": [[0, 0], [1, 1]]})
    assert ok is True
    assert op_type == "line"
    assert err_code == ""
    assert err_msg == ""


def test_validate_draw_op_circle_ok():
    ok, op_type, err_code, err_msg = validate_draw_op({"t": "circle", "cx": 1, "cy": 2, "r": 10})
    assert ok is True
    assert op_type == "circle"


def test_validate_draw_op_rejects_unknown_tool():
    ok, op_type, err_code, err_msg = validate_draw_op({"t": "triangle"})
    assert ok is False
    assert op_type == "triangle"
    assert err_code == "INVALID_OP"


def test_validate_draw_op_rejects_short_line():
    ok, op_type, err_code, err_msg = validate_draw_op({"t": "line", "pts": [[0, 0]]})
    assert ok is False
    assert err_code == "INVALID_LINE"


def test_validate_draw_op_rejects_bad_circle():
    ok, op_type, err_code, err_msg = validate_draw_op({"t": "circle", "cx": 1, "cy": 2})
    assert ok is False
    assert err_code == "INVALID_CIRCLE"


def test_validate_draw_op_accepts_payload_in_p():
    ok, op_type, err_code, err_msg = validate_draw_op({"t": "line", "p": {"pts": [[0, 0], [1, 1]]}})
    assert ok is True
    assert op_type == "line"
