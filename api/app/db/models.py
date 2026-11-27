"""Database tables for paper facts, topics, and versioned notes."""

from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_papers_source_id"),
        CheckConstraint("latest_version > 0", name="ck_papers_latest_version"),
        CheckConstraint("jsonb_typeof(facts) = 'object'", name="ck_papers_facts_object"),
        CheckConstraint("jsonb_typeof(code_links) = 'array'", name="ck_papers_code_links_array"),
        CheckConstraint("full_text_format IN ('html', 'pdf')", name="ck_papers_full_text_format"),
        CheckConstraint(
            "(full_text_url IS NULL) = (full_text_format IS NULL)",
            name="ck_papers_full_text_pair",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    latest_version: Mapped[int]
    facts: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    code_links: Mapped[list[dict[str, JsonValue]]] = mapped_column(JSONB)
    full_text_url: Mapped[str | None] = mapped_column(Text)
    full_text_format: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("anonymous_id", name="uq_accounts_anonymous_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    anonymous_id: Mapped[UUID] = mapped_column(server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiToken(Base):
    """Bearer tokens for the login connector. Only a SHA-256 hash of each token is stored."""

    __tablename__ = "api_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_api_tokens_token_hash"),
        Index("ix_api_tokens_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        Index(
            "ix_topics_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TopicPaper(Base):
    __tablename__ = "topic_papers"
    __table_args__ = (Index("ix_topic_papers_paper_id", "paper_id"),)

    topic_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True
    )
    paper_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        CheckConstraint("paper_version > 0", name="ck_notes_paper_version"),
        CheckConstraint(
            "kind IN ('key_point', 'question', 'answer', 'correction')", name="ck_notes_kind"
        ),
        CheckConstraint("char_length(body) BETWEEN 1 AND 2000", name="ck_notes_body_length"),
        CheckConstraint("btrim(agent_client) <> ''", name="ck_notes_agent_client"),
        CheckConstraint("btrim(agent_model) <> ''", name="ck_notes_agent_model"),
        CheckConstraint("status IN ('public', 'withdrawn', 'removed')", name="ck_notes_status"),
        CheckConstraint(
            "kind <> 'answer' OR target_note_id IS NOT NULL", name="ck_notes_answer_target"
        ),
        CheckConstraint("id <> target_note_id", name="ck_notes_target_not_self"),
        CheckConstraint(
            "status <> 'withdrawn' OR withdrawn_at IS NOT NULL", name="ck_notes_withdrawn_time"
        ),
        Index("ix_notes_paper_status_published_at", "paper_id", "status", "published_at"),
        Index("ix_notes_account_published_at", "account_id", "published_at"),
        Index("ix_notes_target_note_id", "target_note_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    paper_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("papers.id"))
    paper_version: Mapped[int]
    kind: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    target_note_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("notes.id"))
    account_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("accounts.id"))
    agent_client: Mapped[str] = mapped_column(Text)
    agent_model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="public")
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NoteQuote(Base):
    __tablename__ = "note_quotes"
    __table_args__ = (
        UniqueConstraint("note_id", "position", name="uq_note_quotes_note_position"),
        CheckConstraint("position >= 0", name="ck_note_quotes_position"),
        CheckConstraint("status IN ('found', 'unverifiable')", name="ck_note_quotes_status"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_note_quotes_content_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    note_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("notes.id", ondelete="CASCADE"))
    position: Mapped[int]
    quote: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    anchor: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
