"""Add auth tables (users, refresh_tokens) and athletes.user_id.

Revision ID: 20260321_0003
Revises: 20260320_0002
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa

revision = "20260321_0003"
down_revision = "20260320_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # Recovery-sicher: Bei teilweiser, fehlgeschlagener Ausführung nicht erneut crashen.
    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(255), unique=True, index=True, nullable=True),
            sa.Column("password_hash", sa.String(255), nullable=True),
            sa.Column("strava_id", sa.Integer(), unique=True, index=True, nullable=True),
            sa.Column("strava_access_token", sa.String(500), nullable=True),
            sa.Column("strava_refresh_token", sa.String(500), nullable=True),
            sa.Column("strava_token_expires_at", sa.DateTime(), nullable=True),
            sa.Column("first_name", sa.String(100), nullable=True),
            sa.Column("last_name", sa.String(100), nullable=True),
            sa.Column("auth_provider", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )

    if "refresh_tokens" not in tables:
        op.create_table(
            "refresh_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("token_hash", sa.String(64), index=True, nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )

    athlete_columns = {c["name"] for c in inspector.get_columns("athletes")}
    if "user_id" not in athlete_columns:
        op.add_column("athletes", sa.Column("user_id", sa.Integer(), nullable=True))

    inspector = sa.inspect(bind)
    athlete_indexes = {idx["name"] for idx in inspector.get_indexes("athletes")}
    if "ix_athletes_user_id" not in athlete_indexes:
        op.create_index("ix_athletes_user_id", "athletes", ["user_id"], unique=True)

    # SQLite/libSQL kann FK-Constraints per ALTER TABLE nicht hinzufügen.
    if bind.dialect.name != "sqlite":
        fk_names = {fk.get("name") for fk in inspector.get_foreign_keys("athletes")}
        if "fk_athletes_user_id" not in fk_names:
            op.create_foreign_key("fk_athletes_user_id", "athletes", "users", ["user_id"], ["id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    athlete_indexes = {idx["name"] for idx in inspector.get_indexes("athletes")}
    if "ix_athletes_user_id" in athlete_indexes:
        op.drop_index("ix_athletes_user_id", table_name="athletes")

    if bind.dialect.name != "sqlite":
        fk_names = {fk.get("name") for fk in inspector.get_foreign_keys("athletes")}
        if "fk_athletes_user_id" in fk_names:
            op.drop_constraint("fk_athletes_user_id", "athletes", type_="foreignkey")

    athlete_columns = {c["name"] for c in inspector.get_columns("athletes")}
    if "user_id" in athlete_columns:
        op.drop_column("athletes", "user_id")

    tables = set(inspector.get_table_names())
    if "refresh_tokens" in tables:
        op.drop_table("refresh_tokens")
    if "users" in tables:
        op.drop_table("users")
