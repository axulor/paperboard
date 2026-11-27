"""Add readers' reports on notes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-27 16:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "note_reports",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("note_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('spam', 'illegal', 'privacy', 'misleading', 'other')",
            name="ck_note_reports_reason",
        ),
        sa.CheckConstraint(
            "resolution IS NULL OR resolution IN ('removed', 'kept')",
            name="ck_note_reports_resolution",
        ),
        sa.CheckConstraint(
            "(resolution IS NULL) = (resolved_at IS NULL)", name="ck_note_reports_resolved_pair"
        ),
        sa.CheckConstraint("char_length(detail) <= 500", name="ck_note_reports_detail_length"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_note_reports_note_id", "note_reports", ["note_id"], unique=False)
    op.create_index(
        "ix_note_reports_open",
        "note_reports",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("resolution IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_note_reports_open",
        table_name="note_reports",
        postgresql_where=sa.text("resolution IS NULL"),
    )
    op.drop_index("ix_note_reports_note_id", table_name="note_reports")
    op.drop_table("note_reports")
