"""SQLAlchemy-Modelle und Datenbankverbindung.

Lokal: SQLite-Datei.
Production: Turso/libSQL via TURSO_DATABASE_URL + TURSO_AUTH_TOKEN.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from sqlalchemy import ForeignKey, String, Text, create_engine, func, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatabaseSettings:
    mode: str
    database_url: str
    connect_args: dict[str, object]
    auto_create_local_schema: bool


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _with_secure_true(url: str) -> str:
    if "secure=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}secure=true"


def _normalize_turso_url(raw_url: str) -> str:
    if raw_url.startswith("sqlite+libsql://"):
        return _with_secure_true(raw_url)
    if raw_url.startswith("libsql://"):
        return _with_secure_true(f"sqlite+{raw_url}")
    raise RuntimeError(
        "Ungültige TURSO_DATABASE_URL. Erwartet: libsql://... oder sqlite+libsql://..."
    )


def resolve_database_settings(env: Mapping[str, str] | None = None) -> DatabaseSettings:
    source = env or os.environ
    turso_url = source.get("TURSO_DATABASE_URL")
    turso_token = source.get("TURSO_AUTH_TOKEN")

    if bool(turso_url) ^ bool(turso_token):
        raise RuntimeError(
            "Unvollständige Turso-Konfiguration: TURSO_DATABASE_URL und TURSO_AUTH_TOKEN "
            "müssen gemeinsam gesetzt sein."
        )

    if turso_url and turso_token:
        return DatabaseSettings(
            mode="turso",
            database_url=_normalize_turso_url(turso_url),
            connect_args={"auth_token": turso_token},
            auto_create_local_schema=False,
        )

    db_path = source.get("CANOVR_DB_PATH", "canovr.db")
    auto_create_local_schema = _parse_bool(source.get("CANOVR_AUTO_CREATE_SCHEMA"), default=True)
    return DatabaseSettings(
        mode="sqlite",
        database_url=f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        auto_create_local_schema=auto_create_local_schema,
    )


SETTINGS = resolve_database_settings()
DATABASE_URL = SETTINGS.database_url
DATABASE_CONNECT_ARGS = SETTINGS.connect_args
IS_TURSO = SETTINGS.mode == "turso"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args=DATABASE_CONNECT_ARGS,
)
SyncSession = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Athlete(Base):
    __tablename__ = "athletes"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_request_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(100))
    target_distance: Mapped[str] = mapped_column(String(20))
    race_time_seconds: Mapped[float]
    weekly_km: Mapped[float]
    experience_years: Mapped[int]
    current_phase: Mapped[str] = mapped_column(String(20), default="general")
    week_in_phase: Mapped[int] = mapped_column(default=1)
    phase_weeks_total: Mapped[int] = mapped_column(default=8)
    rest_day: Mapped[int | None] = mapped_column(default=None)
    long_run_day: Mapped[int | None] = mapped_column(default=None)
    days_to_race: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    race_results: Mapped[list[RaceResult]] = relationship(back_populates="athlete", order_by="RaceResult.date.desc()")
    completed_workouts: Mapped[list[CompletedWorkout]] = relationship(back_populates="athlete", order_by="CompletedWorkout.date.desc()")
    week_plans: Mapped[list[WeekPlan]] = relationship(back_populates="athlete", order_by="WeekPlan.created_at.desc()")
    pace_history: Mapped[list[PaceHistory]] = relationship(back_populates="athlete", order_by="PaceHistory.date.desc()")


class RaceResult(Base):
    __tablename__ = "race_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    date: Mapped[dt.date]
    distance: Mapped[str] = mapped_column(String(20))
    time_seconds: Mapped[float]
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    athlete: Mapped[Athlete] = relationship(back_populates="race_results")


class CompletedWorkout(Base):
    __tablename__ = "completed_workouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    date: Mapped[dt.date]
    workout_key: Mapped[str] = mapped_column(String(50))
    zone: Mapped[str | None] = mapped_column(String(10), default=None)
    distance_km: Mapped[float | None] = mapped_column(default=None)
    duration_minutes: Mapped[float | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    athlete: Mapped[Athlete] = relationship(back_populates="completed_workouts")


class WeekPlan(Base):
    __tablename__ = "week_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    phase: Mapped[str] = mapped_column(String(20))
    week_in_phase: Mapped[int]
    plan_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    athlete: Mapped[Athlete] = relationship(back_populates="week_plans")


class PaceHistory(Base):
    __tablename__ = "pace_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    athlete_id: Mapped[int] = mapped_column(ForeignKey("athletes.id"))
    date: Mapped[dt.date]
    old_race_time_seconds: Mapped[float]
    new_race_time_seconds: Mapped[float]
    strategy: Mapped[str] = mapped_column(String(30))
    improvement_pct: Mapped[float]
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now())

    athlete: Mapped[Athlete] = relationship(back_populates="pace_history")


def _validate_turso_schema() -> None:
    """Production-Guard: Schema muss bereits per Alembic migriert sein."""
    try:
        inspector = inspect(engine)
        required_tables = (
            "alembic_version",
            "athletes",
            "race_results",
            "completed_workouts",
            "week_plans",
            "pace_history",
        )
        missing = [table for table in required_tables if not inspector.has_table(table)]
        if missing:
            raise RuntimeError(
                "Turso-Schema unvollständig oder nicht migriert. "
                "Führe 'alembic upgrade head' aus. "
                f"Fehlende Tabellen: {', '.join(missing)}"
            )
    except SQLAlchemyError as exc:
        raise RuntimeError("Turso-Schema konnte nicht geprüft werden.") from exc


def _should_auto_migrate_turso() -> bool:
    return _parse_bool(os.environ.get("CANOVR_AUTO_MIGRATE_TURSO"), default=True)


def _alembic_ini_path() -> Path:
    configured = os.environ.get("ALEMBIC_CONFIG")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "alembic.ini"


def _run_alembic_upgrade_head() -> None:
    try:
        from alembic import command
        from alembic.config import Config
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Alembic ist nicht importierbar. Stelle sicher, dass die Dependency installiert ist."
        ) from exc

    alembic_ini = _alembic_ini_path()
    if not alembic_ini.exists():
        raise RuntimeError(
            f"Alembic-Konfiguration nicht gefunden: {alembic_ini}. "
            "Migration kann nicht ausgeführt werden."
        )

    try:
        config = Config(str(alembic_ini))
        command.upgrade(config, "head")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Automatische Turso-Migration (alembic upgrade head) fehlgeschlagen.") from exc


def init_db() -> None:
    """Initialisiere DB-Verbindung und validiere/verwalte Schema."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise RuntimeError("Datenbank-Verbindung fehlgeschlagen.") from exc

    if IS_TURSO:
        if _should_auto_migrate_turso():
            LOGGER.info("Turso: Starte alembic upgrade head (idempotent).")
            _run_alembic_upgrade_head()
        _validate_turso_schema()
        return

    if SETTINGS.auto_create_local_schema:
        Base.metadata.create_all(engine)
