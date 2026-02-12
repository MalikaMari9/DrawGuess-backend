# app/main.py
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from app.settings import get_settings
from app.store.redis_repo import RedisRepo
from app.transport.admin import router as admin_router
from app.transport.ws import router as ws_router
from app.transport.ws_manager import WSManager


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME)
    allowed_origins = [o.strip() for o in settings.WS_ALLOWED_ORIGINS.split(",") if o.strip()]
    if "null" not in allowed_origins:
        allowed_origins.append("null")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    app.include_router(admin_router)
    return app




app = create_app()
