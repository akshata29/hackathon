# Workshop Module 05: Build Your MCP Server

## Objective

Build the private MCP server that gives your CONFIDENTIAL agents access to proprietary data.
You will implement row-level security so that each user only sees their own data.

If your application has no confidential data and all agents use public APIs, you can
skip to the public data integration section and move on to Module 06.

---

## What is MCP?

**Model Context Protocol** is an open standard for AI agents to consume external tools over HTTP.
An MCP server exposes a catalogue of named tools. Agents discover tools at runtime by calling
`tools/list`, then invoke them via `tools/call`.

Benefits over plain REST APIs:
- The agent receives **tool descriptions** and uses them to decide when and how to call a tool
- Structured input/output schemas reduce prompt engineering for tool calling
- The same server can be shared across multiple agents or workflows

The reference server uses **FastMCP**, a Python library that turns decorated functions into
fully-compliant MCP tools with automatic schema generation.

---

## Step 1 — Run the Reference Portfolio DB MCP Server

Study the reference implementation before building yours:

```bash
cd d:\repos\hackathon\mcp-servers\portfolio-db
pip install -r requirements.txt
MCP_AUTH_TOKEN=dev-token python server.py
```

> **Auth modes**: The server uses `EntraTokenVerifier` from `entra_auth.py`.
> When `ENTRA_TENANT_ID` is **not set**, it falls back to comparing the static `MCP_AUTH_TOKEN`
> so you can run locally without Entra credentials.
> In production, the backend exchanges the user's Entra token for an OBO token
> and passes it as the Bearer token — the MCP server then extracts user identity from the JWT.

Test with the dev-mode static token:

```powershell
# List tools
Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8002/mcp" `
    -Headers @{ "Authorization"="Bearer dev-token" } `
    -ContentType "application/json" `
    -Body '{"method": "tools/list", "params": {}}'

# Call a tool
Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8002/mcp" `
    -Headers @{ "Authorization"="Bearer dev-token" } `
    -ContentType "application/json" `
    -Body '{"method": "tools/call", "params": {"name": "get_holdings", "arguments": {}}}'
```

Open [mcp-servers/portfolio-db/server.py](../../mcp-servers/portfolio-db/server.py) and study:

1. How `get_user_id_from_request()` is called inside each tool to obtain the caller's
   stable identity from the verified JWT claims (or dev fallback)
2. How the user ID is used to filter database queries (row-level security)
3. How `EntraTokenVerifier` / `MultiIDPTokenVerifier` is configured in `entra_auth.py`
4. How `check_scope()` and `audit_log()` are used for scope enforcement and traceability

---

## Step 2 — Run Coding Prompt Step 4 (Private MCP Server)

Open GitHub Copilot Chat (agent mode). Paste and fill in:

> Full prompt in [template/docs/coding-prompts/README.md](../../template/docs/coding-prompts/README.md) — Step 4.

```
I need to build a private MCP server for my application "<YOUR APP NAME>" using FastMCP.

The server will expose the following tools:
1. Tool name: <tool_1_name>
   Description: <what it does, shown to the agent>
   Parameters: <list each param: name, type, description, required/optional>
   Returns: <describe the return structure>
   Data source: <where the data comes from — Cosmos DB, SQL, REST API, etc.>

2. Tool name: <tool_2_name>
   Description: <what it does>
   Parameters: <params>
   Returns: <return structure>

Row-level security requirement:
- Call get_user_id_from_request() inside each tool to get the authenticated caller's
  stable user_id from the verified JWT (or dev fallback token)
- Queries must be scoped to that user_id; no user should ever see another user's data
- Return an empty result (not an error) if no data exists for that user

Authentication:
- Use EntraTokenVerifier from entra_auth.py (copy from template/mcp-servers/my-mcp/)
  Production: validates Entra OBO JWT; dev fallback: static MCP_AUTH_TOKEN when
  ENTRA_TENANT_ID is not set
- Call check_scope("<resource>.read") at the start of every confidential tool
- Wrap each tool with audit_log(tool_name, user_id, outcome, duration_ms)
- Return HTTP 401 if token is missing or invalid

Place the server at `my-app/mcp-servers/my-mcp/server.py`
Copy entra_auth.py from template/mcp-servers/my-mcp/entra_auth.py
Follow the same pattern as mcp-servers/portfolio-db/server.py

For the data store, use <your chosen store — Cosmos DB with DefaultAzureCredential,
SQLite for local dev, a REST API, etc.>.

For local development, add seed data so I can test all tools without a real backend.
Add the seed data in a `data/` directory or as an inline constant in the file.
```

---

## Step 3 — Start and Test Your MCP Server

```bash
cd my-app\mcp-servers\my-mcp
pip install -r requirements.txt
MCP_AUTH_TOKEN=dev-token python server.py
# Expected: Listening on http://0.0.0.0:8003
```

Test each tool (dev mode — `ENTRA_TENANT_ID` not set, static token fallback active):

```powershell
# List available tools
Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8003/mcp" `
    -Headers @{ "Authorization"="Bearer dev-token" } `
    -ContentType "application/json" `
    -Body '{"method": "tools/list", "params": {}}'

# Test a specific tool
$call = @{
    method = "tools/call"
    params = @{
        name = "<tool_1_name>"
        arguments = @{ <param> = "<value>" }
    }
} | ConvertTo-Json -Depth 3

Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8003/mcp" `
    -Headers @{ "Authorization"="Bearer dev-token" } `
    -ContentType "application/json" `
    -Body $call
```

> **Row-level isolation in dev mode**: in dev mode, `get_user_id_from_request()` returns
> `"dev-user"` for the static token — all dev requests share one identity.
> For multi-user isolation testing, set `ENTRA_TENANT_ID` and use real Entra OBO tokens.

Test the 401 rejection — send a request with a wrong token and confirm HTTP 401 is returned:

```powershell
Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8003/mcp" `
    -Headers @{ "Authorization"="Bearer wrong-token" } `
    -ContentType "application/json" `
    -Body '{"method": "tools/list", "params": {}}'
# Expected: 401 Unauthorized
```

---

## Step 4 — Connect the MCP Server to Your Agent

Open the CONFIDENTIAL agent file you created in Module 04. Ensure the MCP tool is wired:

In production, the backend acquires an OBO token for the MCP server scope and passes it
as the Bearer token. The MCP server extracts user identity from the JWT — no `X-User-Id`
header is needed. For local dev, the static token fallback is used:

```python
from agent_framework.mcp import MCPStreamableHTTPTool

def create_my_agent(client, raw_token: str) -> Agent:
    # raw_token is the Entra OBO token from the backend auth middleware
    # (falls back to settings.mcp_auth_token in dev mode)
    mcp_tool = MCPStreamableHTTPTool(
        name="my-mcp",
        url=f"{settings.my_mcp_url}",
        approval_mode="auto",
        headers={
            "Authorization": f"Bearer {raw_token}",
        },
    )
    return Agent(
        client=client,
        name="my_agent",
        instructions=INSTRUCTIONS,
        tools=[mcp_tool],
        require_per_service_call_history_persistence=True,
    )
```

The `raw_token` is the OBO token extracted by `require_auth_context()` in `chat.py`
and threaded through to `build_specialist_agents()` in the workflow.
See `backend/app/workflows/portfolio_workflow.py` for the full pattern.

Update `my-app/backend/.env` with:

```
MY_MCP_URL=http://localhost:8003/mcp
MCP_AUTH_TOKEN=dev-token
```

---

## Step 5 — (Optional) Add a Public External Data Source

If one of your agents needs public data (market APIs, government data, news feeds),
run Coding Prompt Step 5:

> Full prompt in [template/docs/coding-prompts/README.md](../../template/docs/coding-prompts/README.md) — Step 5.

This prompt helps you either:
- Connect to an **existing public MCP server** (e.g., a FRED economic data MCP, a news MCP)
- Wrap a **REST API** as a `FunctionTool` — a simpler alternative to a full MCP server

For public data without row-level security, a `FunctionTool` is usually simpler:

```python
from agent_framework import FunctionTool

async def get_sector_news(sector: str) -> list[dict]:
    """Fetch the latest 5 news headlines for a given industry sector.

    Args:
        sector: Industry sector name (e.g. "banking", "insurance", "technology")

    Returns:
        List of {title, source, published_at, summary} dicts
    """
    # call your API here
    ...

news_tool = FunctionTool(fn=get_sector_news)
```

---

## Step 6 — End-to-End Test with MCP Data

With both the backend and your MCP server running, test a query that should trigger a
tool call in the CONFIDENTIAL agent:

```powershell
$body = @{
    message = "<query that requires data from your MCP server>"
    session_id = "test-mcp-e2e-01"
} | ConvertTo-Json

Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8000/api/chat/message" `
    -ContentType "application/json" `
    -Body $body
```

In the response SSE stream you should see:
1. `type: "handoff"` — routing to your CONFIDENTIAL agent
2. `type: "tool_call"` — the agent calling your MCP tool
3. `type: "tool_result"` — the MCP server returning data
4. `type: "text_delta"` — the agent synthesising the response
5. `type: "message_complete"` — done

---

## Verification Checkpoint

- [ ] `my-mcp/server.py` starts and listens on port 8003
- [ ] `tools/list` returns all your defined tools with descriptions
- [ ] Row-level security verified: two users see different data
- [ ] 401 returned for invalid auth token
- [ ] End-to-end test shows `tool_call` + `tool_result` events in SSE stream
- [ ] Agent response contains real data from your MCP server (not hallucinated)

---

## Next: [Module 06 — RAG, Domain Data & Frontend](./06-security-guardrails.md)
