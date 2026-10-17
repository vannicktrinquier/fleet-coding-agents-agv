"""Application factory.

Serve with ``uvicorn --factory app.main:create_app``. Configuration comes from
``LIBRARY_*`` environment variables (see the README).
"""

import logging
import warnings
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__, books, db, fines, loans, members, reports
from app.clock import Clock, SystemClock
from app.config import Settings
from app.errors import LibraryError

logger = logging.getLogger(__name__)


async def _handle_library_error(request: Request, exc: Exception) -> JSONResponse:
    error = exc if isinstance(exc, LibraryError) else LibraryError(str(exc))
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail})


def create_app(
    db_path: str | Path | None = None,
    clock: Clock | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    """Build the API on top of the SQLite database at ``db_path``.

    Pending migrations are applied before the app is returned. Tests pass a
    temporary ``db_path`` and a ``FixedClock``; in production both come from
    the environment and the system clock.
    """
    settings = settings if settings is not None else Settings.from_env()
    clock = clock if clock is not None else SystemClock()
    path = Path(db_path) if db_path is not None else settings.db_path
    db.migrate(path, clock.now())

    if not settings.admin_api_key.strip():
        logger.warning("LIBRARY_ADMIN_KEY is not set; admin endpoints are disabled")
        warnings.warn(
            "LIBRARY_ADMIN_KEY is not set; admin endpoints are disabled",
            UserWarning,
            stacklevel=2,
        )

    app = FastAPI(
        title="Lending Library",
        version=__version__,
        description="Catalog, members, loans and fines for a small lending library.",
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.db_path = path
    app.add_exception_handler(LibraryError, _handle_library_error)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str | None]:
        return {"status": "ok", "version": __version__, "schema": db.schema_version(path)}

    for router in (books.router, members.router, loans.router, fines.router, reports.router):
        app.include_router(router)
    return app
