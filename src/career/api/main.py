"""The application: one FastAPI app, server-rendered, no build step.

Served by uvicorn as a single process behind `max_replicas = 1`. A personal
tool with occasional data entry and a job review queue has no reason for a
separate SPA build.

**`/healthz` and `/readyz` are different on purpose.** Container Apps uses
the liveness probe to decide whether to restart the container. If that probe
touched storage, a blob blip would restart every replica and turn a brief
outage into a crash loop. So `/healthz` answers from memory alone, and
`/readyz` is the one that reaches the profile blob.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from appkit import csrf, headers, health
from appkit.integrity import IntegrityError
from fastapi import Depends, FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..settings import secret, settings
from . import deps, routes

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Resolve the passcode once when the process starts.

    `secret` is cached after this call, so a changed Key Vault value takes
    effect on the next container start rather than on an arbitrary first
    request. Storage remains lazy: a brief blob outage should fail a
    request, not prevent the app starting.
    """
    if settings().require_passcode:
        secret("APP-PASSCODE")
    yield


def _ready() -> None:
    """Readiness: the cheapest read that proves storage is reachable."""
    from .. import store

    store.load_profile()


def create_app() -> FastAPI:
    cfg = settings()
    app = FastAPI(
        title="career",
        description="Career profile, job-opportunity aggregation and market/advancement insights.",
        lifespan=lifespan,
        # No interactive docs: this serves HTML to one person, and an
        # OpenAPI page is surface area behind the same passcode for no
        # benefit.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    # Before headers, so a cross-site refusal carries the security headers too.

    csrf.install(app)

    headers.install(app)

    # /healthz from memory (reporting IMAGE_TAG as `version` for the smoke
    # test), /readyz through a real read of storage: see the module docstring.
    health.install(app, environment=cfg.environment, ready=_ready)

    # Login is the one route outside the gate, for obvious reasons.
    app.include_router(routes.public)
    app.include_router(routes.router, dependencies=[Depends(deps.require_session)])

    static = routes.STATIC_DIR
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=static), name="static")

    @app.exception_handler(IntegrityError)
    async def _broken(_request: Any, exc: IntegrityError) -> JSONResponse:
        """A change the store refused because the document would break one of
        its rules: a route or pipeline bug the form checks missed. Nothing was
        written. The detail names positions and board ids, never values."""
        logger.error("write refused: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": f"Not saved: {exc}"},
        )

    @app.exception_handler(routes.ConflictResponse)
    async def _conflict(_request: Any, exc: routes.ConflictResponse) -> JSONResponse:
        """A write that lost its race twice, after the one retry in
        `store.update_*`. Surfaced rather than swallowed: the person needs to
        know their edit was not recorded, since they are the only one who
        can re-enter it.
        """
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc)},
        )

    return app


app = create_app()
