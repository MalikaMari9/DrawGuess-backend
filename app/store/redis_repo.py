# app/store/redis_repo.py
from __future__ import annotations

import json
from typing import Any, Optional, Iterable, Literal

from redis.asyncio import Redis

from app.store.redis_keys import RK
from app.store.models import PlayerStore, RoomHeaderStore, DrawOp, ModLogEntry

Mode = Literal["SINGLE", "VS"]


class RedisRepo:
    def __init__(self, r: Redis, room_ttl_sec: int = 1800):
        self.r = r
        self.room_ttl_sec = room_ttl_sec

    def _dec(self, x):
            """Decode redis bytes -> str; pass through str/int/None safely."""
            if x is None:
                return None
            if isinstance(x, bytes):
                return x.decode("utf-8")
            return x

    def _dec_map(self, d: dict) -> dict:
            return {self._dec(k): self._dec(v) for k, v in d.items()}


    # ----------------------------
    # Helpers
    # ----------------------------
    async def refresh_room_ttl(self, room_code: str, mode: Mode) -> None:
        rk = RK(room_code)
        keys = rk.all_room_keys(mode=mode)

        # Pipeline: expire everything
        pipe = self.r.pipeline()
        for k in keys:
            pipe.expire(k, self.room_ttl_sec)
        await pipe.execute()

    async def room_exists(self, room_code: str) -> bool:
        return bool(await self.r.exists(RK(room_code).room()))

    # ----------------------------
    # Room header
    # ----------------------------
    async def create_room(self, room_code: str, header: RoomHeaderStore) -> None:
        rk = RK(room_code)
        # Store as Redis hash
        await self.r.hset(rk.room(), mapping=header.model_dump(exclude_none=True))
        # Ensure empty structures exist (optional but nice)
        pipe = self.r.pipeline()
        pipe.delete(rk.players(), rk.active(), rk.connections(), rk.roles(), rk.round_config(),
                    rk.game(), rk.budget(), rk.cooldown(), rk.ratelimit(), rk.votes_next(), rk.modlog(),
                    rk.ops(), rk.ops_team("A"), rk.ops_team("B"), rk.team("A"), rk.team("B"), rk.teams_meta())
        await pipe.execute()

    async def get_room_header(self, room_code: str) -> Optional[RoomHeaderStore]:
        rk = RK(room_code)
        data = await self.r.hgetall(rk.room())
        if not data:
            return None
        # redis returns bytes sometimes depending config; normalize
        norm = self._dec_map(data)

        # ints
        for f in ["cap", "created_at", "last_activity", "round_no"]:
            if f in norm and norm[f] != "":
                norm[f] = int(norm[f])
        return RoomHeaderStore(**norm)

    async def update_room_fields(self, room_code: str, **fields: Any) -> None:
        rk = RK(room_code)
        await self.r.hset(rk.room(), mapping=fields)

    # ----------------------------
    # Players
    # ----------------------------
    async def add_player(self, room_code: str, player: PlayerStore) -> None:
        rk = RK(room_code)
        await self.r.hset(rk.players(), player.pid, player.model_dump_json())
        await self.r.sadd(rk.active(), player.pid)

    async def set_player_connected(self, room_code: str, pid: str, connected: bool, ts: int) -> None:
        rk = RK(room_code)
        raw = await self.r.hget(rk.players(), pid)
        if not raw:
            return
        p = PlayerStore.model_validate_json(self._dec(raw))
        p.connected = connected
        p.last_seen = ts
        await self.r.hset(rk.players(), pid, p.model_dump_json())
        if connected:
            await self.r.sadd(rk.active(), pid)
        else:
            await self.r.srem(rk.active(), pid)

    async def update_player_fields(self, room_code: str, pid: str, **fields: Any) -> None:
        rk = RK(room_code)
        raw = await self.r.hget(rk.players(), pid)
        if not raw:
            return
        p = PlayerStore.model_validate_json(self._dec(raw))
        for k, v in fields.items():
            setattr(p, k, v)
        await self.r.hset(rk.players(), pid, p.model_dump_json())

    async def get_player(self, room_code: str, pid: str) -> Optional[PlayerStore]:
        rk = RK(room_code)
        raw = await self.r.hget(rk.players(), pid)
        if not raw:
            return None
        return PlayerStore.model_validate_json(self._dec(raw))

    async def list_players(self, room_code: str) -> list[PlayerStore]:
        rk = RK(room_code)
        data = await self.r.hgetall(rk.players())
        players: list[PlayerStore] = []
        for _, raw in data.items():
            players.append(PlayerStore.model_validate_json(self._dec(raw)))
        # stable order: joined_at
        players.sort(key=lambda x: x.joined_at)
        return players

    # ----------------------------
    # Roles / teams
    # ----------------------------
    async def set_roles(self, room_code: str, roles: dict[str, str]) -> None:
        # roles: {"gm": pid, "drawer": pid} OR {"drawerA": pidA, "drawerB": pidB}
        await self.r.hset(RK(room_code).roles(), mapping=roles)

    async def get_roles(self, room_code: str) -> dict[str, str]:
        data = await self.r.hgetall(RK(room_code).roles())
        return {self._dec(k): self._dec(v) for k, v in data.items()}

    async def set_team(self, room_code: str, pid: str, team: Literal["A", "B"]) -> None:
        rk = RK(room_code)
        # remove from both then add
        pipe = self.r.pipeline()
        pipe.srem(rk.team("A"), pid)
        pipe.srem(rk.team("B"), pid)
        pipe.sadd(rk.team(team), pid)
        await pipe.execute()

        # ALSO persist on player record (snapshot reads this)
        await self.update_player_fields(room_code, pid, team=team)


    async def get_team_members(self, room_code: str, team: Literal["A", "B"]) -> set[str]:
        members = await self.r.smembers(RK(room_code).team(team))
        return {self._dec(x) for x in members}

    # ----------------------------
    # Round config & live game
    # ----------------------------
    async def set_round_config(self, room_code: str, cfg: dict[str, Any]) -> None:
        # store as hash strings
        rk = RK(room_code)
        mapping = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in cfg.items()}
        await self.r.hset(rk.round_config(), mapping=mapping)

    async def get_round_config(self, room_code: str) -> dict[str, Any]:
        rk = RK(room_code)
        data = await self.r.hgetall(rk.round_config())
        out: dict[str, Any] = {}
        for k, v in data.items():
            ks = self._dec(k)
            vs = self._dec(v)
            # best-effort json parse
            try:
                out[ks] = json.loads(vs)
            except Exception:
                out[ks] = vs
        return out

    async def set_game_fields(self, room_code: str, **fields: Any) -> None:
        rk = RK(room_code)
        mapping = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v) for k, v in fields.items()}
        await self.r.hset(rk.game(), mapping=mapping)

    async def get_game(self, room_code: str) -> dict[str, Any]:
        rk = RK(room_code)
        data = await self.r.hgetall(rk.game())
        out: dict[str, Any] = {}
        for k, v in data.items():
            ks = self._dec(k)
            vs = self._dec(v)
            try:
                out[ks] = json.loads(vs)
            except Exception:
                out[ks] = vs
        return out

    # ----------------------------
    # Ops log (replay) Stroke
    # ----------------------------
    async def append_op_single(self, room_code: str, op: DrawOp, max_ops: int = 5000) -> None:
        rk = RK(room_code)
        pipe = self.r.pipeline()
        pipe.rpush(rk.ops(), op.model_dump_json())
        pipe.ltrim(rk.ops(), -max_ops, -1)
        await pipe.execute()

    async def append_op_vs(self, room_code: str, team: Literal["A", "B"], op: DrawOp, max_ops: int = 5000) -> None:
        rk = RK(room_code)
        pipe = self.r.pipeline()
        pipe.rpush(rk.ops_team(team), op.model_dump_json())
        pipe.ltrim(rk.ops_team(team), -max_ops, -1)
        await pipe.execute()

    async def get_ops_single(self, room_code: str, start: int = 0, end: int = -1) -> list[DrawOp]:
        raw = await self.r.lrange(RK(room_code).ops(), start, end)
        return [DrawOp.model_validate_json(self._dec(x)) for x in raw]

    async def get_ops_vs(self, room_code: str, team: Literal["A", "B"], start: int = 0, end: int = -1) -> list[DrawOp]:
        raw = await self.r.lrange(RK(room_code).ops_team(team), start, end)
        return [DrawOp.model_validate_json(self._dec(x)) for x in raw]

    async def clear_ops(self, room_code: str, mode: Mode) -> None:
        rk = RK(room_code)
        if mode == "VS":
            await self.r.delete(rk.ops_team("A"), rk.ops_team("B"))
        else:
            await self.r.delete(rk.ops())

    # ----------------------------
    # Budget / cooldown (non-atomic version first)
    # ----------------------------
    async def set_budget_fields(self, room_code: str, **fields: Any) -> None:
        rk = RK(room_code)
        mapping = {k: str(v) for k, v in fields.items()}
        await self.r.hset(rk.budget(), mapping=mapping)

    async def get_budget(self, room_code: str) -> dict[str, int]:
        rk = RK(room_code)
        data = await self.r.hgetall(rk.budget())
        out: dict[str, int] = {}
        for k, v in data.items():
            out[self._dec(k)] = int(self._dec(v))
        return out

    async def set_cooldown_fields(self, room_code: str, **fields: Any) -> None:
        rk = RK(room_code)
        mapping = {k: str(v) for k, v in fields.items()}
        await self.r.hset(rk.cooldown(), mapping=mapping)

    async def get_cooldown(self, room_code: str) -> dict[str, int]:
        rk = RK(room_code)
        data = await self.r.hgetall(rk.cooldown())
        return {self._dec(k): int(self._dec(v)) for k, v in data.items()}

    # ----------------------------
    # Voting
    # ----------------------------
    async def vote_next_add(self, room_code: str, pid: str) -> int:
        # returns current vote count
        rk = RK(room_code)
        await self.r.sadd(rk.votes_next(), pid)
        return int(await self.r.scard(rk.votes_next()))
