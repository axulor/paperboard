"""Create initial tables.

Revision ID: 0001
Revises:
Create Date: 2026-11-26 14:45:40.570214
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "anonymous_id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("anonymous_id", name="uq_accounts_anonymous_id"),
    )
    op.create_table(
        "papers",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("facts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("code_links", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("full_text_url", sa.Text(), nullable=True),
        sa.Column("full_text_format", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "full_text_format IN ('html', 'pdf')", name="ck_papers_full_text_format"
        ),
        sa.CheckConstraint("jsonb_typeof(code_links) = 'array'", name="ck_papers_code_links_array"),
        sa.CheckConstraint("jsonb_typeof(facts) = 'object'", name="ck_papers_facts_object"),
        sa.CheckConstraint(
            "(full_text_url IS NULL) = (full_text_format IS NULL)", name="ck_papers_full_text_pair"
        ),
        sa.CheckConstraint("latest_version > 0", name="ck_papers_latest_version"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_id", name="uq_papers_source_id"),
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_topics_title_trgm",
        "topics",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_table(
        "notes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("paper_id", sa.BigInteger(), nullable=False),
        sa.Column("paper_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("target_note_id", sa.BigInteger(), nullable=True),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("agent_client", sa.Text(), nullable=False),
        sa.Column("agent_model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="public", nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("btrim(agent_client) <> ''", name="ck_notes_agent_client"),
        sa.CheckConstraint("btrim(agent_model) <> ''", name="ck_notes_agent_model"),
        sa.CheckConstraint(
            "kind <> 'answer' OR target_note_id IS NOT NULL", name="ck_notes_answer_target"
        ),
        sa.CheckConstraint(
            "kind IN ('key_point', 'question', 'answer', 'correction')", name="ck_notes_kind"
        ),
        sa.CheckConstraint(
            "status <> 'withdrawn' OR withdrawn_at IS NOT NULL", name="ck_notes_withdrawn_time"
        ),
        sa.CheckConstraint("status IN ('public', 'withdrawn', 'removed')", name="ck_notes_status"),
        sa.CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="ck_notes_body_length"),
        sa.CheckConstraint("id <> target_note_id", name="ck_notes_target_not_self"),
        sa.CheckConstraint("paper_version > 0", name="ck_notes_paper_version"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_note_id"],
            ["notes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notes_account_published_at", "notes", ["account_id", "published_at"], unique=False
    )
    op.create_index(
        "ix_notes_paper_status_published_at",
        "notes",
        ["paper_id", "status", "published_at"],
        unique=False,
    )
    op.create_index("ix_notes_target_note_id", "notes", ["target_note_id"], unique=False)
    op.create_table(
        "topic_papers",
        sa.Column("topic_id", sa.BigInteger(), nullable=False),
        sa.Column("paper_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("topic_id", "paper_id"),
    )
    op.create_index("ix_topic_papers_paper_id", "topic_papers", ["paper_id"], unique=False)
    op.create_table(
        "note_quotes",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("note_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("anchor", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_note_quotes_content_hash"),
        sa.CheckConstraint("status IN ('found', 'unverifiable')", name="ck_note_quotes_status"),
        sa.CheckConstraint("position >= 0", name="ck_note_quotes_position"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "position", name="uq_note_quotes_note_position"),
    )


def downgrade() -> None:
    op.drop_table("note_quotes")
    op.drop_table("topic_papers")
    op.drop_table("notes")
    op.drop_table("topics")
    op.drop_table("papers")
    op.drop_table("accounts")
    # Keep pg_trgm available to other tables in this database.
