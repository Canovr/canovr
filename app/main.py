"""CanovR — Full-Spectrum Training Reasoner.

Litestar-Backend mit PyReason-basierter Inferenz für die
Full-Spectrum Percentage-Based Trainingsmethode nach John Davis.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Awaitable, Callable

from litestar import Litestar, get
from litestar.middleware import DefineMiddleware
from litestar.openapi import OpenAPIConfig
from litestar.openapi.spec import Contact, Tag

from app.athlete_routes import AthleteController
from app.database import init_db
from app.routes import TrainingController

LOGGER = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app: Callable[..., Awaitable[Any]]) -> None:
        self.app = app

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[Any]],
        send: Callable[..., Awaitable[Any]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "-")
        path = scope.get("path", "-")
        scope_headers = list(scope.get("headers", []))
        headers = dict(scope_headers)
        request_id = (
            headers.get(b"x-request-id", b"").decode().strip()
            or headers.get(b"x-cloud-trace-context", b"").decode().split("/", maxsplit=1)[0]
            or str(uuid.uuid4())
        )
        if b"x-request-id" not in headers:
            scope_headers.append((b"x-request-id", request_id.encode()))
            scope["headers"] = scope_headers
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
                raw_headers = list(message.get("headers", []))
                raw_headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = raw_headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            if status_code == 429:
                error_class = "rate_limited_429"
            elif status_code == 504:
                error_class = "upstream_timeout_504"
            elif status_code == 503:
                error_class = "no_available_instance"
            elif status_code >= 500:
                error_class = "server_error"
            else:
                error_class = "none"

            LOGGER.info(
                "request.complete request_id=%s path=%s method=%s status=%s duration_ms=%.2f error_class=%s",
                request_id,
                path,
                method,
                status_code,
                duration_ms,
                error_class,
            )


@get("/", tags=["System"])
async def index() -> dict[str, str]:
    """App-Info und Version."""
    return {
        "app": "CanovR",
        "version": "0.2.0",
        "swagger": "/schema/swagger",
    }


async def on_startup() -> None:
    init_db()


app = Litestar(
    route_handlers=[index, TrainingController, AthleteController],
    middleware=[DefineMiddleware(RequestLoggingMiddleware)],
    on_startup=[on_startup],
    debug=True,
    openapi_config=OpenAPIConfig(
        title="CanovR",
        version="0.2.0",
        description=(
            "Full-Spectrum Percentage-Based Training Reasoner.\n\n"
            "Basierend auf der Methode von John Davis (runningwritings.com), "
            "implementiert mit **54 PyReason-Regeln** als logischem Backbone.\n\n"
            "## Features\n"
            "- **Training Recommend**: Workout-Empfehlungen via PyReason-Inferenz\n"
            "- **Week Planner**: 7-Tage-Plan mit Constraint-Solving\n"
            "- **Pace Update**: 3 Strategien (Fitness, Evolution, Bridging)\n"
            "- **Athlete Management**: Profil, Rennen, Workout-Tracking\n"
            "- **Taper**: Automatische Volumenreduktion vor Wettkampf\n"
            "- **Progression**: Base → Volume → Extension → Recovery\n"
        ),
        contact=Contact(name="CanovR", url="https://runningwritings.com"),
        tags=[
            Tag(name="System", description="App-Info und Status"),
            Tag(
                name="Training",
                description=(
                    "Trainingsempfehlungen, Wochenplanung und Pace-Updates. "
                    "Keine Persistenz — alle Daten pro Request."
                ),
            ),
            Tag(
                name="Athletes",
                description=(
                    "Athleten-Management mit SQLite-Persistenz. "
                    "CRUD, Rennergebnisse, Workout-Tracking, DB-gestützte Wochenplanung."
                ),
            ),
        ],
    ),
)
