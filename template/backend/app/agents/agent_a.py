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

        Option b — MCPStreamableHTTPTool (connects to your private MCP server):
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


