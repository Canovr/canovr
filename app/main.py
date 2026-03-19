"""CanovR — Full-Spectrum Training Reasoner.

Litestar-Backend mit PyReason-basierter Inferenz für die
Full-Spectrum Percentage-Based Trainingsmethode nach John Davis.
"""

from __future__ import annotations

from litestar import Litestar, get
from litestar.openapi import OpenAPIConfig
from litestar.openapi.spec import Contact, Tag

from app.athlete_routes import AthleteController
from app.database import init_db
from app.routes import TrainingController


@get("/", tags=["System"])
async def index() -> dict[str, str]:
    """App-Info und Version."""
    return {
        "app": "CanovR",
        "version": "0.2.0",
        "swagger": "/schema/swagger",
    }


async def on_startup() -> None:
    await init_db()
    # PyReason beim Serverstart aufwärmen (JIT + Graph)
    try:
        from app.reasoner import run_inference
        from app.models import AthleteInput
        a = AthleteInput(
            target_distance="10k", race_time_seconds=2700, weekly_km=30,
            experience_years=3, current_phase="general", days_since_hard_workout=99,
        )
        run_inference(a)
        print("PyReason warmup completed")
    except Exception as e:
        print(f"PyReason warmup failed: {e}")


app = Litestar(
    route_handlers=[index, TrainingController, AthleteController],
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
