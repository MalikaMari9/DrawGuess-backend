from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.store.redis_keys import RK

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/rooms")
async def list_rooms(request: Request):
    """
    List all active rooms (debug/admin).
    """
    repo = request.app.state.repo
    r = request.app.state.redis

    # Scan for room header keys: room:<code>
    cursor = 0
    room_codes = []
    while True:
        cursor, keys = await r.scan(cursor=cursor, match="room:*", count=200)
        for k in keys:
            key = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
            # keep only room header keys: room:<code>
            if key.count(":") == 1:
                room_codes.append(key.split(":")[1])
        if cursor == 0:
            break

    rooms = []
    for code in sorted(set(room_codes)):
        header = await repo.get_room_header(code)
        if header is None:
            continue
        players = await repo.list_players(code)
        connected = [p for p in players if p.connected]
        rooms.append(
            {
                "room_code": code,
                "mode": header.mode,
                "state": header.state,
                "cap": header.cap,
                "round_no": header.round_no,
                "players": len(players),
                "connected": len(connected),
                "last_activity": header.last_activity,
                "created_at": header.created_at,
            }
        )

    return {"rooms": rooms}


@router.post("/rooms/{room_code}/close")
async def close_room(room_code: str, request: Request):
    """
    Force close a room (debug/admin). Deletes Redis keys and closes websockets.
    """
    repo = request.app.state.repo
    r = request.app.state.redis
    wsman = request.app.state.wsman

    header = await repo.get_room_header(room_code)
    if header is None:
        raise HTTPException(status_code=404, detail="Room not found")

    rk = RK(room_code)
    keys = rk.all_room_keys(mode=header.mode)
    await r.delete(*keys)

    # Close all websockets in room if any
    # wsman has no room close; use internal map
    room = getattr(wsman, "_rooms", {}).get(room_code, {})
    for pid in list(room.keys()):
        try:
            await wsman.close_pid(room_code, pid, code=4000, reason="admin_close")
        except Exception:
            pass

    return {"ok": True, "room_code": room_code}
