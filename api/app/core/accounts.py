"""Accounts and the bearer tokens that log them in to the connector.

A token is shown once, when it is made; only its SHA-256 hash is stored. Tokens are long random
strings, so a plain hash is enough to look them up without keeping them.
"""

import hashlib
import secrets
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Account, ApiToken

TOKEN_PREFIX = "pb_"


class IssuedToken(BaseModel):
    account_id: int
    anonymous_id: UUID
    token: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_account_with_token(
    sessions: async_sessionmaker[AsyncSession], label: str
) -> IssuedToken:
    """A new account and a token for it."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    async with sessions.begin() as session:
        account = Account()
        session.add(account)
        await session.flush()
        session.add(ApiToken(account_id=account.id, token_hash=hash_token(token), label=label))
        await session.flush()
        await session.refresh(account)
        return IssuedToken(account_id=account.id, anonymous_id=account.anonymous_id, token=token)


async def account_for_token(sessions: async_sessionmaker[AsyncSession], token: str) -> int | None:
    """The account a token belongs to, or None if it is unknown or revoked."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    async with sessions() as session:
        return await session.scalar(
            select(ApiToken.account_id).where(
                ApiToken.token_hash == hash_token(token), ApiToken.revoked_at.is_(None)
            )
        )
