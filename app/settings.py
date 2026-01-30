# app/settings.py
from __future__ import annotations

from pydantic import BaseModel
import os


class Settings(BaseModel):
    APP_NAME: str = "drawguess-server"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    ROOM_TTL_SEC: int = 1800

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Dev
    LOG_LEVEL: str = "INFO"

    # ✅ WebSocket origin policy (comma-separated)
    WS_ALLOWED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,null"
    # ✅ Dev helper: allow any private LAN IP on port 5173
    WS_ALLOW_LAN_ORIGINS: bool = True


def get_settings() -> Settings:
    return Settings(
        APP_NAME=os.getenv("APP_NAME", "drawguess-server"),
        REDIS_URL=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        ROOM_TTL_SEC=int(os.getenv("ROOM_TTL_SEC", "1800")),
        HOST=os.getenv("HOST", "0.0.0.0"),
        PORT=int(os.getenv("PORT", "8000")),
        LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),

        WS_ALLOWED_ORIGINS=os.getenv(
            "WS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,null",
        ),
        WS_ALLOW_LAN_ORIGINS=os.getenv("WS_ALLOW_LAN_ORIGINS", "true").lower()
        in ("1", "true", "yes", "y", "on"),
    )
