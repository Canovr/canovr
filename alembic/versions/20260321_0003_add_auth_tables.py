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

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), index=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.add_column("athletes", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_athletes_user_id", "athletes", "users", ["user_id"], ["id"])
    op.create_index("ix_athletes_user_id", "athletes", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_athletes_user_id", table_name="athletes")
    op.drop_constraint("fk_athletes_user_id", "athletes", type_="foreignkey")
    op.drop_column("athletes", "user_id")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
