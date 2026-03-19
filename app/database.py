"""SQLAlchemy-Modelle und Datenbankverbindung.

Turso (libSQL) für Produktion, lokale SQLite für Entwicklung.
"""

from __future__ import annotations

import datetime as dt
import os

from sqlalchemy import ForeignKey, String, Text, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


# Turso: TURSO_DATABASE_URL + TURSO_AUTH_TOKEN gesetzt → remote
# Lokal: sqlite:///canovr.db
_turso_url = os.environ.get("TURSO_DATABASE_URL")
_turso_token = os.environ.get("TURSO_AUTH_TOKEN")

if _turso_url and _turso_token:
    # sqlite+libsql://... format für sqlalchemy-libsql
    _url = _turso_url.replace("libsql://", "sqlite+libsql://")
    DATABASE_URL = f"{_url}?secure=true&auth_token={_turso_token}"
    print(f"DB: Turso ({_turso_url})")
else:
    _db_path = os.environ.get("CANOVR_DB_PATH", "canovr.db")
    DATABASE_URL = f"sqlite:///{_db_path}"
    print(f"DB: Local SQLite ({_db_path})")

engine = create_engine(DATABASE_URL, echo=False)
SyncSession = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Athlete(Base):
    __tablename__ = "athletes"

    id: Mapped[int] = mapped_column(primary_key=True)
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


def init_db() -> None:
    """Erstelle alle Tabellen."""
    Base.metadata.create_all(engine)
