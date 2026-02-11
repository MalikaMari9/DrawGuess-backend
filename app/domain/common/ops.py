from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple


def _op_field(op_data: Dict[str, Any], key: str) -> Any:
    if key in op_data:
        return op_data.get(key)
    p = op_data.get("p")
    if isinstance(p, dict) and key in p:
        return p.get(key)
    return None


def validate_draw_op(
    op_data: Dict[str, Any],
    *,
    allow_tools: Iterable[str] = ("line", "circle"),
) -> Tuple[bool, str, str, str]:
    """
    Validate a draw op payload.
    Returns (ok, op_type, err_code, err_message).
    """
    if not isinstance(op_data, dict):
        return False, "", "INVALID_OP", "Draw op must be an object"

    op_type = op_data.get("t", "line")
    if op_type not in allow_tools:
        return False, op_type, "INVALID_OP", f"Invalid operation type: {op_type}. Only 'line' and 'circle' are allowed."

    if op_type == "line":
        pts = _op_field(op_data, "pts")
        if not isinstance(pts, list) or len(pts) < 2:
            return False, op_type, "INVALID_LINE", "Line operation requires at least 2 points"

    if op_type == "circle":
        cx = _op_field(op_data, "cx")
        cy = _op_field(op_data, "cy")
        r = _op_field(op_data, "r")
        if cx is None or cy is None or r is None:
            return False, op_type, "INVALID_CIRCLE", "Circle operation requires 'cx', 'cy' and 'r'"
        if not isinstance(r, (int, float)) or r < 0 or r > 1000:
            return False, op_type, "INVALID_RADIUS", "Circle radius must be between 0 and 1000"

    return True, op_type, "", ""
