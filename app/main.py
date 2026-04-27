"""CanovR — Full-Spectrum Training Reasoner.

Litestar-Backend mit PyReason-basierter Inferenz für die
Full-Spectrum Percentage-Based Trainingsmethode nach John Davis.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Awaitable, Callable

from litestar import Litestar, MediaType, Request, Response, get
from litestar.di import Provide
from litestar.exceptions import NotFoundException
from litestar.logging import LoggingConfig
from litestar.middleware import DefineMiddleware
from litestar.openapi import OpenAPIConfig
from litestar.openapi.spec import Contact, Tag

from app.env_loader import load_environment

load_environment()

from app.athlete_routes import AthleteController
from app.auth_guard import provide_current_user
from app.auth_models import User  # noqa: F401 — ensures SQLAlchemy mapper sees it
from app.auth_routes import AuthController
from app.database import init_db
from app.routes import TrainingController

LOGGER = logging.getLogger(__name__)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ios_app_id() -> str:
    team_id = os.environ.get("CANOVR_APPLE_TEAM_ID", "M944LR67TZ").strip()
    bundle_id = os.environ.get("CANOVR_IOS_BUNDLE_ID", "com.canovr.app").strip()
    return f"{team_id}.{bundle_id}"


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


@get("/", tags=["System"], exclude_from_auth=True)
async def index() -> dict[str, str]:
    """App-Info und Version."""
    return {
        "app": "CanovR",
        "version": "0.3.0",
        "swagger": "/schema/swagger",
    }


AASA_RESPONSE = {
    "applinks": {
        "apps": [],
        "details": [
            {
                "appID": _ios_app_id(),
                "paths": ["/auth/strava/callback"],
            }
        ],
    }
}

STRAVA_CALLBACK_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>CanovR</title></head>
<body style="font-family:system-ui;text-align:center;padding:60px">
<h2>CanovR</h2>
<p>Falls die App nicht automatisch geöffnet wurde,<br>öffne CanovR manuell.</p>
</body></html>"""


@get("/.well-known/apple-app-site-association", media_type=MediaType.JSON, exclude_from_auth=True)
async def apple_app_site_association() -> dict:
    """Apple App Site Association für Universal Links."""
    return AASA_RESPONSE


@get("/auth/strava/callback", media_type=MediaType.HTML, exclude_from_auth=True)
async def strava_callback() -> str:
    """Strava OAuth Callback — wird von iOS als Universal Link abgefangen.

    Falls iOS den Link nicht abfängt, zeigt eine Fallback-Seite.
    """
    return STRAVA_CALLBACK_HTML


PRIVACY_POLICY_HTML = """<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Datenschutzerklärung — CanovR</title>
<style>body{font-family:system-ui,sans-serif;max-width:700px;margin:0 auto;padding:24px;color:#1a1a1a;line-height:1.6}
h1{font-size:1.4em}h2{font-size:1.1em;margin-top:2em}a{color:#2563eb}</style></head>
<body>
<h1>Datenschutzerklärung</h1>
<p><strong>CanovR</strong> — App für Lauftrainingsplanung<br>
Stand: März 2026</p>

<h2>1. Verantwortlicher</h2>
<p>Raphael Feikert<br>Robert-Bosch-Straße 7<br>64293 Darmstadt<br>
E-Mail: <a href="mailto:info@canovr.com">info@canovr.com</a></p>

<h2>2. Welche Daten wir erheben</h2>
<ul>
<li><strong>Account-Daten:</strong> E-Mail-Adresse und Name (bei E-Mail-Registrierung) oder Strava-Profildaten (Vorname, Nachname, Strava-ID) bei Strava-Anmeldung.</li>
<li><strong>Trainingsdaten:</strong> Zieldistanz, Wettkampfzeit, Wochenkilometer, Erfahrungsjahre, Trainingsphase, absolvierte Workouts, Rennergebnisse und Pace-Verlauf.</li>
<li><strong>Technische Daten:</strong> IP-Adresse, Request-IDs und Zeitstempel zur Fehleranalyse (Server-Logs).</li>
</ul>

<h2>3. Zweck der Verarbeitung</h2>
<p>Wir verarbeiten deine Daten ausschließlich zur Bereitstellung der Trainingspläne und Funktionen der App (Art. 6 Abs. 1 lit. b DSGVO — Vertragserfüllung).</p>

<h2>4. Strava-Integration</h2>
<p>Bei Anmeldung über Strava verarbeiten wir dein Strava-Profil (Vorname, Nachname, Strava-ID) und einen kurzlebigen OAuth-Code zur Authentifizierung. Wir speichern keine dauerhaften Strava Access- oder Refresh-Tokens in unserer Datenbank und greifen nicht auf deine Strava-Aktivitäten zu. Du kannst den Zugriff jederzeit in deinen <a href="https://www.strava.com/settings/apps">Strava-Einstellungen</a> widerrufen.</p>

<h2>5. Speicherung und Hosting</h2>
<p>Daten werden auf Servern von Google Cloud Run (Region us-central1) gespeichert. Die Datenbank wird bei Turso (libSQL) gehostet. Alle Verbindungen sind TLS-verschlüsselt.</p>

<h2>6. Weitergabe an Dritte</h2>
<p>Wir geben keine personenbezogenen Daten an Dritte weiter, außer an die technischen Dienstleister (Google Cloud, Turso), die als Auftragsverarbeiter agieren.</p>

<h2>7. Deine Rechte</h2>
<p>Du hast das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch. Kontaktiere uns unter <a href="mailto:info@canovr.com">info@canovr.com</a>.</p>

<h2>8. Account-Löschung</h2>
<p>Du kannst deinen Account jederzeit in der App unter Profil &gt; „Account löschen" unwiderruflich löschen. Dabei werden alle deine Daten (Account, Trainingsdaten, Rennergebnisse) vollständig entfernt.</p>

<h2>9. Cookies und Tracking</h2>
<p>Die App und das Backend verwenden keine Cookies, kein Tracking und keine Analyse-Tools.</p>

<h2>10. Änderungen</h2>
<p>Bei wesentlichen Änderungen dieser Datenschutzerklärung informieren wir dich über die App.</p>
</body></html>"""

IMPRESSUM_HTML = """<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Impressum — CanovR</title>
<style>body{font-family:system-ui,sans-serif;max-width:700px;margin:0 auto;padding:24px;color:#1a1a1a;line-height:1.6}
h1{font-size:1.4em}h2{font-size:1.1em;margin-top:2em}a{color:#2563eb}</style></head>
<body>
<h1>Impressum</h1>
<h2>Angaben gemäß § 5 TMG</h2>
<p>Raphael Feikert<br>Robert-Bosch-Straße 7<br>64293 Darmstadt</p>
<h2>Kontakt</h2>
<p>E-Mail: <a href="mailto:info@canovr.com">info@canovr.com</a></p>
<h2>Verantwortlich für den Inhalt nach § 55 Abs. 2 RStV</h2>
<p>Raphael Feikert<br>Robert-Bosch-Straße 7<br>64293 Darmstadt</p>
</body></html>"""


@get("/privacy", media_type=MediaType.HTML, exclude_from_auth=True)
async def privacy_policy() -> str:
    """Datenschutzerklärung."""
    return PRIVACY_POLICY_HTML


@get("/impressum", media_type=MediaType.HTML, exclude_from_auth=True)
async def impressum() -> str:
    """Impressum (§ 5 TMG)."""
    return IMPRESSUM_HTML


def _warmup_pyreason() -> None:
    """Background-Warmup: JIT-kompiliert PyReason ohne Startup zu blockieren."""
    try:
        from app.models import AthleteInput
        from app.reasoner import run_inference

        dummy = AthleteInput(
            target_distance="10k", race_time_seconds=2700, weekly_km=30,
            experience_years=3, current_phase="general", days_since_hard_workout=99,
        )
        started = time.perf_counter()
        run_inference(dummy)
        duration_ms = (time.perf_counter() - started) * 1000
        LOGGER.info("pyreason.warmup.success duration_ms=%.2f", duration_ms)
    except Exception:
        LOGGER.exception("pyreason.warmup.failed")


async def on_startup() -> None:
    init_db()
    threading.Thread(target=_warmup_pyreason, daemon=True).start()


def _handle_not_found(_: Request, exc: NotFoundException) -> Response:
    return Response(
        media_type=MediaType.JSON,
        status_code=404,
        content={"status_code": 404, "detail": exc.detail},
    )


def _exception_logging_handler(logger: logging.Logger, scope: Any, tb: list[str]) -> None:
    # Skip NotFoundException — 404s are normal traffic, not unhandled errors.
    if tb and "NotFoundException" in tb[-1]:
        return
    logger.exception(
        "Uncaught exception (connection_type=%s, path=%r):",
        scope["type"],
        scope["path"],
    )


app = Litestar(
    route_handlers=[
        index,
        apple_app_site_association,
        strava_callback,
        privacy_policy,
        impressum,
        AuthController,
        TrainingController,
        AthleteController,
    ],
    dependencies={"current_user": Provide(provide_current_user, sync_to_thread=True)},
    exception_handlers={NotFoundException: _handle_not_found},
    logging_config=LoggingConfig(exception_logging_handler=_exception_logging_handler),
    middleware=[DefineMiddleware(RequestLoggingMiddleware)],
    on_startup=[on_startup],
    debug=_parse_bool(os.environ.get("CANOVR_DEBUG"), default=False),
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
