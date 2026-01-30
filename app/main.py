# app/main.py
from __future__ import annotations

from fastapi import FastAPI
from redis.asyncio import Redis

from app.settings import get_settings
from app.store.redis_repo import RedisRepo
from app.transport.ws import router as ws_router
from app.transport.ws_manager import WSManager


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME)

    @app.on_event("startup")
    async def _startup() -> None:
        r = Redis.from_url(settings.REDIS_URL, decode_responses=False)
        app.state.redis = r
        app.state.repo = RedisRepo(r, room_ttl_sec=settings.ROOM_TTL_SEC)
        app.state.wsman = WSManager()
        await r.ping()


    @app.on_event("shutdown")
    async def _shutdown() -> None:
        r: Redis = app.state.redis
        await r.close()

    @app.get("/health")
    async def health():
        r: Redis = app.state.redis
        pong = await r.ping()
        return {"ok": True, "redis": str(pong)}

    app.include_router(ws_router)
    return app




app = create_app()
