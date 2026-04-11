# ============================================================
# My MCP Server — TEMPLATE STUB
# Exposes domain-specific data tools via the Model Context Protocol.
# The backend connects to this server via MCPStreamableHTTPTool.
#
# When to build a private MCP server:
#   - Your data is private/confidential (user portfolios, internal databases)
#   - You need row-level security (X-User-Id header enforcement)
#   - You want to audit, rate-limit, or transform data before it reaches agents
#
# When to use a hosted/public MCP instead:
#   - Data is already available as a public MCP (e.g. Alpha Vantage, GitHub)
#   - Reference: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol
#
# Coding prompt: See template/docs/coding-prompts/README.md > Step 4
# Example implementations:
#   mcp-servers/portfolio-db/server.py   (private, row-level security)
#   mcp-servers/yahoo-finance/server.py  (semi-public, bearer token auth)
# ============================================================

import logging
import os

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth — shared bearer token validated by FastMCP
# The backend sends this token in its Authorization header.
# In production, retrieve from Azure Key Vault (see mcp-servers/yahoo-finance/keyvault.py).
# ---------------------------------------------------------------------------
_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "dev-mcp-token-change-me")
auth_provider = StaticTokenVerifier(
    tokens={_AUTH_TOKEN: {"sub": "backend-service", "client_id": "backend"}}
)

mcp = FastMCP(
    name="my-mcp-server",                       # TODO: rename
    instructions=(
        "You have access to <describe your data here>. "
        "Use these tools to <describe what the agent should do with this data>. "
        "Data classification: PUBLIC | CONFIDENTIAL  # TODO: choose one"
    ),
    auth=auth_provider,
)

# ---------------------------------------------------------------------------
# Row-level security helper (use for CONFIDENTIAL data)
# ---------------------------------------------------------------------------
#
# If your data is per-user, the backend passes the authenticated user's identity
# in the X-User-Id header. Enforce it like this:
#
#   from fastmcp.server import Context
#
#   @mcp.tool()
#   async def get_user_data(ctx: Context) -> dict:
#       user_id = ctx.request.headers.get("X-User-Id", "")
#       if not user_id:
#           return {"error": "Missing X-User-Id header"}
#       return fetch_data_for_user(user_id)


# ---------------------------------------------------------------------------
# Tools — add your domain tools below
# ---------------------------------------------------------------------------

@mcp.tool()
def get_item(id: str) -> dict:
    """
    Retrieve a single item by ID.

    Args:
        id: The unique identifier for the item.

    Returns:
        dict with item details, or {id, error} on failure.

    TODO: Replace this stub with a real data fetch from your database or API.
    """
    # TODO: replace with real implementation
    # Example:
    #   import sqlite3
    #   conn = sqlite3.connect(os.getenv("DB_PATH", "data.db"))
    #   row = conn.execute("SELECT * FROM items WHERE id = ?", (id,)).fetchone()
    #   return dict(row) if row else {"id": id, "error": "Not found"}
    return {"id": id, "description": "stub — implement me"}


@mcp.tool()
def list_items(category: str = "") -> list[dict]:
    """
    List items, optionally filtered by category.

    Args:
        category: Optional filter. Leave empty to return all items.

    Returns:
        List of item dicts, each with {id, name, category}.

    TODO: Replace with real database query or API call.
    """
    # TODO: replace with real implementation
    return [
        {"id": "1", "name": "Example Item A", "category": "example"},
        {"id": "2", "name": "Example Item B", "category": "example"},
    ]


if __name__ == "__main__":
    import uvicorn
    # Run with: python server.py
    # Or via Docker using the Dockerfile in this directory.
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)
