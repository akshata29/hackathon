# ============================================================
# Specialist Agent A — TEMPLATE STUB
#
# Extend BaseAgent to define a domain-specific specialist.
# One agent = one area of expertise + one set of tools.
#
# Coding prompt: See template/docs/coding-prompts/README.md > Step 2
# Example implementations:
#   backend/app/agents/portfolio_data.py — private MCP (MCPStreamableHTTPTool)
#   backend/app/agents/economic_data.py  — REST API (FunctionTool)
#   backend/app/agents/market_intel.py   — Foundry Prompt Agent (override create())
# ============================================================

import logging

from app.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — defines what this agent knows and what it can discuss
# ---------------------------------------------------------------------------
AGENT_A_INSTRUCTIONS = """
You are a specialist in <YOUR DOMAIN HERE>.

Your responsibilities:
- <describe what this agent does>
- <describe what data sources / tools it uses>
- <describe its scope — what it DOES and DOES NOT handle>

Data classification: PUBLIC  # or CONFIDENTIAL — affects routing + guardrail boundaries
""".strip()


class AgentA(BaseAgent):
    """Domain specialist agent — TODO: rename and fill in details."""

    name = "agent_a"
    description = "<What this agent does — shown in handoff decisions>"
    system_message = AGENT_A_INSTRUCTIONS

    @classmethod
    def build_tools(cls, **kwargs) -> list:
        """
        Return this agent's tools.  Pick one of the three patterns below.

        Option a — Python FunctionTool (wraps a REST API or local function):
            from agent_framework import FunctionTool

            async def my_lookup(query: str) -> str:
                \"\"\"Look up <something> given a query.\"\"\"
                # ... call your API here
                return result

            return [FunctionTool(name="my_lookup", description=my_lookup.__doc__ or "", func=my_lookup)]

        Option c -- MCPStreamableHTTPTool with VENDOR OAuth token (external MCP, Pattern 2):
            # Used for external vendor MCPs (GitHub, Salesforce, etc.) that have their
            # own OAuth identity system and cannot accept Entra OBO tokens.
            #
            # The token is obtained once via OAuth2 Authorization Code flow and stored
            # per-user in VendorOAuthStore (Cosmos DB). At agent call time the workflow
            # pre-fetches it and passes it here.
            #
            # See: app/core/auth/vendor_oauth_store.py
            #      app/routes/github_auth.py  (reference implementation)
            #      backend/app/agents/github_intel.py (reference implementation)
            import httpx
            from agent_framework import MCPStreamableHTTPTool

            vendor_token = kwargs.get("vendor_token")   # per-user OAuth token from VendorOAuthStore
            vendor_mcp_url = kwargs.get("vendor_mcp_url", "https://vendor.example.com/mcp/")

            if vendor_token:
                http_client = httpx.AsyncClient(
                    headers={"Authorization": f"Bearer {vendor_token}"},
                    timeout=30,
                )
                return [MCPStreamableHTTPTool(url=vendor_mcp_url, http_client=http_client)]

            # No token -- user hasn't authorized; return a guidance FunctionTool
            from agent_framework import FunctionTool

            async def not_connected(query: str) -> str:
                """Look up data from <vendor>."""
                return "<Vendor> is not connected. Visit /api/auth/<vendor> to connect."

            return [FunctionTool(name="vendor_lookup", description=not_connected.__doc__ or "", func=not_connected)]
            import httpx
            from agent_framework import MCPStreamableHTTPTool
            from app.core.auth.obo import build_obo_http_client

            # kwargs must include: mcp_url, raw_token, mcp_auth_token (dev fallback), settings
            mcp_url      = kwargs["mcp_url"]
            raw_token    = kwargs.get("raw_token")
            fallback_tok = kwargs.get("mcp_auth_token", "dev-my-mcp-token")
            settings     = kwargs.get("settings")

            # Production: OBO exchange --> MCP receives a user-bound token
            # Dev mode:   plain Bearer fallback (when ENTRA_CLIENT_SECRET not set)
            http_client = build_obo_http_client(
                settings=settings,
                raw_token=raw_token,
                mcp_client_id=settings.my_mcp_client_id if settings else "",
                scope_name="my-scope.read",
                fallback_bearer=fallback_tok,
            ) if settings else httpx.AsyncClient(
                headers={"Authorization": f"Bearer {fallback_tok}"}
            )

            return [MCPStreamableHTTPTool(
                url=mcp_url,
                http_client=http_client,
            )]
            import httpx
            from agent_framework import MCPStreamableHTTPTool

            mcp_url = kwargs.get("mcp_url", "")
            mcp_auth_token = kwargs.get("mcp_auth_token", "")
            http_client = httpx.AsyncClient(headers={"Authorization": f"Bearer {mcp_auth_token}"})
            return [MCPStreamableHTTPTool(name="MyTool", url=f"{mcp_url}/mcp",
                                          approval_mode="never_require", http_client=http_client)]

        Option c — Hosted Foundry Prompt Agent (override create() instead of build_tools):
            Override the entire create() classmethod as shown in market_intel.py.
            Hosted agents have their tools configured server-side in Foundry portal.
        """
        # TODO: replace with your actual tool(s)
        return []


# Backward-compat factory — prefer AgentA.create() in new code
def create_agent_a(client, **kwargs):
    return AgentA.create(client, **kwargs)


