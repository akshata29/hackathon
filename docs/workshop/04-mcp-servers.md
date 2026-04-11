# Workshop Module 04: MCP Servers

## Learning Objectives
- Understand Model Context Protocol (MCP) as a tool integration standard
- Run and test the Yahoo Finance and Portfolio DB MCP servers
- Connect MCP tools to an agent using `get_mcp_tool()`
- Implement row-level security in an MCP server

## What is MCP?

MCP (Model Context Protocol) is an open standard that allows AI agents to consume external tools
over HTTP. The backend uses `client.get_mcp_tool()` to connect agents to MCP-compatible servers.

```python
# Connect an agent to an MCP server
mcp_tool = client.get_mcp_tool(
    name="yahoo-finance",
    url="http://yahoo-mcp:8001/mcp",
    approval_mode="auto",          # auto-approve tool calls
    headers={"X-User-Id": user_id},  # propagate user context
)
```

## Running MCP Servers Locally

### Yahoo Finance MCP
```bash
cd mcp-servers/yahoo-finance
pip install -r requirements.txt
MCP_AUTH_TOKEN=dev-token python server.py
```

Test:
```bash
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-token" \
  -d '{"method": "tools/call", "params": {"name": "get_quote", "arguments": {"symbol": "AAPL"}}}'
```

### Portfolio DB MCP
```bash
cd mcp-servers/portfolio-db
pip install -r requirements.txt
MCP_AUTH_TOKEN=dev-token python server.py
```

Test with row-level security:
```bash
curl -X POST http://localhost:8002/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-token" \
  -H "X-User-Id: user-001" \
  -d '{"method": "tools/call", "params": {"name": "get_holdings", "arguments": {}}}'
```

Note how different `X-User-Id` values return different (isolated) data.

## FastMCP Tool Authoring

```python
from fastmcp import FastMCP

mcp = FastMCP(name="my-mcp-server")

@mcp.tool()
def get_data(param: str) -> dict:
    """
    Tool description — shown to the agent in the tool catalog.

    Args:
        param: Description of the parameter

    Returns:
        dict with result
    """
    return {"result": f"Data for {param}"}
```

## Exercise 1: Add a new tool to Yahoo Finance MCP

Add a `get_historical_prices` tool to `mcp-servers/yahoo-finance/server.py`:

```python
@mcp.tool()
def get_historical_prices(symbol: str, period: str = "1mo") -> list[dict]:
    """
    Get historical daily closing prices.

    Args:
        symbol: Stock ticker symbol
        period: Time period — one of: 1mo, 3mo, 6mo, 1y, 2y, 5y

    Returns:
        List of dicts with date and close price
    """
    ticker = yf.Ticker(symbol.upper())
    hist = ticker.history(period=period)
    return [
        {"date": str(idx.date()), "close": round(row["Close"], 2)}
        for idx, row in hist.iterrows()
    ]
```

Then restart the server and verify the tool appears in `tools/list`.

## Exercise 2: Connect the new tool to an agent

In `backend/app/agents/private_data.py`, the Yahoo Finance MCP tool is already wired up.
After adding the new tool, ask the agent: "Show me AAPL price history for the last 3 months".

## Key Code References
- [mcp-servers/yahoo-finance/server.py](../../mcp-servers/yahoo-finance/server.py)
- [mcp-servers/portfolio-db/server.py](../../mcp-servers/portfolio-db/server.py)
- [backend/app/agents/private_data.py](../../backend/app/agents/private_data.py)

## Next: [Module 05 — RAG with AI Search](./05-rag-search.md)
