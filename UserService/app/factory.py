from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, load_settings
from .db import close_engine, init_db, init_engine
from .routers import admin, auth, frps_plugin, tunnels, user
from .services.billing import billing_loop
from .services.frps_api import FrpsAPI

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    start_poller: bool = True,
) -> FastAPI:
    settings = settings or load_settings()
    init_engine(settings.database.url)
    frps = FrpsAPI(settings.frps)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.server.auto_create_tables:
            await init_db()
        task: asyncio.Task | None = None
        if start_poller:
            task = asyncio.create_task(billing_loop(settings, app.state.frps))
            app.state.billing_task = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            close = getattr(app.state.frps, "close", None)
            if close is not None:
                await close()
            await close_engine()

    app = FastAPI(title="QZ-FRP User Service", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.frps = frps

    if settings.server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.server.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(auth.router)
    app.include_router(user.router)
    app.include_router(tunnels.router)
    app.include_router(admin.router)
    app.include_router(frps_plugin.router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict:
        return {"status": "ok"}

    return app
