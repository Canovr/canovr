"""Initial schema for CanovR.

Revision ID: 20260319_0001
Revises:
Create Date: 2026-03-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260319_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "athletes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("target_distance", sa.String(length=20), nullable=False),
        sa.Column("race_time_seconds", sa.Float(), nullable=False),
        sa.Column("weekly_km", sa.Float(), nullable=False),
        sa.Column("experience_years", sa.Integer(), nullable=False),
        sa.Column("current_phase", sa.String(length=20), nullable=False),
        sa.Column("week_in_phase", sa.Integer(), nullable=False),
        sa.Column("phase_weeks_total", sa.Integer(), nullable=False),
        sa.Column("rest_day", sa.Integer(), nullable=True),
        sa.Column("long_run_day", sa.Integer(), nullable=True),
        sa.Column("days_to_race", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "completed_workouts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("workout_key", sa.String(length=50), nullable=False),
        sa.Column("zone", sa.String(length=10), nullable=True),
        sa.Column("distance_km", sa.Float(), nullable=True),
        sa.Column("duration_minutes", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pace_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("old_race_time_seconds", sa.Float(), nullable=False),
        sa.Column("new_race_time_seconds", sa.Float(), nullable=False),
        sa.Column("strategy", sa.String(length=30), nullable=False),
        sa.Column("improvement_pct", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "race_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("distance", sa.String(length=20), nullable=False),
        sa.Column("time_seconds", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "week_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("athlete_id", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("week_in_phase", sa.Integer(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("week_plans")
    op.drop_table("race_results")
    op.drop_table("pace_history")
    op.drop_table("completed_workouts")
    op.drop_table("athletes")
