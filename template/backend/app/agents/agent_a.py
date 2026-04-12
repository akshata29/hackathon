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

        Option d — A2A remote agent (wraps an external Agent-to-Agent server):
            Use this when the specialist logic runs in a SEPARATE process or container
            and communicates via the A2A (Agent-to-Agent) HTTP/JSON-RPC protocol.
            The remote server can be built with ANY framework (LangChain, Semantic
            Kernel, AutoGen, etc.) — the A2A protocol makes it framework-agnostic.

            The A2AAgent is a drop-in replacement for a local Agent: HandoffBuilder
            and ConcurrentBuilder treat it identically.

            Override create_from_context() instead of build_tools():

            @classmethod
            def create_from_context(cls, ctx):
                service_url = getattr(ctx.settings, "my_a2a_service_url", "")
                if not service_url:
                    return None   # silently skip when URL not configured
                from agent_framework_a2a import A2AAgent
                return A2AAgent(url=service_url, name=cls.name, description=cls.description)

            Configure in .env:
                MY_A2A_SERVICE_URL=http://localhost:8010

            Reference implementation:
                backend/app/agents/esg_advisor.py
                a2a-agents/esg-advisor/server.py  (LangChain ReAct server stub)
        """
        # TODO: replace with your actual tool(s)
        return []

    @classmethod
    def create_from_context(cls, ctx: "AgentBuildContext"):
        """Registry hook — called by the orchestrator's dynamic build loop.

        Extract whatever config this agent needs from ctx and call create().
        Return None to opt out (e.g. a required URL is not set in this environment).

        TODO: replace the example below with your agent's actual config needs.

        Example — FunctionTool or MCPStreamableHTTPTool agent:
            return cls.create(
                ctx.client,
                mcp_url=ctx.settings.agent_a_mcp_url,
                raw_token=ctx.raw_token,
                settings=ctx.settings,
            )

        Example — A2A remote agent (option d above):
            url = getattr(ctx.settings, "agent_a_a2a_url", "")
            if not url:
                return None
            from agent_framework_a2a import A2AAgent
            return A2AAgent(url=url, name=cls.name, description=cls.description)
        """
        from app.core.agents.base import AgentBuildContext  # noqa: F401
        # TODO: implement for your agent
        return cls.create(ctx.client)


# Backward-compat factory — prefer AgentA.create() in new code
def create_agent_a(client, **kwargs):
    return AgentA.create(client, **kwargs)


