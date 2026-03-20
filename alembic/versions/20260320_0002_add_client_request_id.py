"""Add client_request_id for idempotent athlete creation.

Revision ID: 20260320_0002
Revises: 20260319_0001
Create Date: 2026-03-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260320_0002"
down_revision = "20260319_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "athletes",
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_athletes_client_request_id",
        "athletes",
        ["client_request_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_athletes_client_request_id", table_name="athletes")
    op.drop_column("athletes", "client_request_id")
