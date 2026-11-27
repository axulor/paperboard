"""Who is calling the login connector.

The connector only needs a TokenVerifier (the MCP SDK's interface): today it checks the
development tokens in the database; GitHub and email login will issue tokens behind the same
interface.
"""

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.accounts import account_for_token

CLIENT_ID = "paperboard"


class AccountTokenVerifier(TokenVerifier):
    """Accepts tokens stored (as hashes) in the api_tokens table."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def verify_token(self, token: str) -> AccessToken | None:
        account_id = await account_for_token(self._sessions, token)
        if account_id is None:
            return None
        return AccessToken(token=token, client_id=CLIENT_ID, scopes=[], subject=str(account_id))


def current_account() -> int:
    """The account of the current request. Only the login connector has one."""
    token = get_access_token()
    if token is None or token.subject is None:
        raise ToolError("Not logged in. Writing needs the login connector address and a token.")
    return int(token.subject)
