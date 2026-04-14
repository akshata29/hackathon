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

from dotenv import load_dotenv
load_dotenv()

from fastmcp import FastMCP
from entra_auth import (
    EntraTokenVerifier,    # single Entra tenant
    MultiIDPTokenVerifier, # Entra + additional OIDC IdPs (set TRUSTED_ISSUERS env var)
    get_user_id_from_request,
    check_scope,
    audit_log,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth -- choose one:
#   EntraTokenVerifier:    Entra ID only (production default)
#   MultiIDPTokenVerifier: Entra + extra OIDC IdPs (set TRUSTED_ISSUERS env var)
#
# Dev mode (ENTRA_TENANT_ID not set):
#   Both verifiers fall back to static token comparison against MCP_AUTH_TOKEN.
# ---------------------------------------------------------------------------
auth_provider = EntraTokenVerifier()
# auth_provider = MultiIDPTokenVerifier()  # uncomment to enable multi-IDP support

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
# Row-level security helper
# ---------------------------------------------------------------------------
#
# For CONFIDENTIAL data, get the authenticated caller's ID and use it to
# scope every query:
#
#   import time
#   from entra_auth import check_scope, get_user_id_from_request, audit_log
#
#   @mcp.tool()
#   async def get_user_data() -> dict:
#       check_scope("my-resource.read")  # scope defined in your app registration
#       user_id = get_user_id_from_request()
#       start = time.monotonic()
#       try:
#           result = fetch_data_for_user(user_id)
#           audit_log("get_user_data", user_id, "success", (time.monotonic()-start)*1000)
#           return result
#       except Exception as exc:
#           audit_log("get_user_data", user_id, "error", error=str(exc))
#           raise


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
