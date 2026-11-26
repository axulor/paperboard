from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from app import VERSION

LOCAL_HOSTS = ["localhost", "127.0.0.1", "[::1]", "localhost:*", "127.0.0.1:*", "[::1]:*"]


def build_mcp_server() -> MCPServer:
    """The PaperBoard connector. Tools are registered here as they are implemented."""
    return MCPServer(name="paperboard", title="PaperBoard", version=VERSION)


def build_mcp_app(server: MCPServer, public_hosts: list[str]) -> Starlette:
    """Streamable HTTP app serving the connector at /mcp.

    Stateless with plain JSON responses: any worker can answer any request, and clients that do
    not speak SSE still work. Host checking guards against DNS rebinding; only localhost and the
    configured public hosts are accepted.
    """
    hosts = LOCAL_HOSTS + public_hosts
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=[f"http://{h}" for h in hosts] + [f"https://{h}" for h in public_hosts],
    )
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
