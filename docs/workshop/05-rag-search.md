# Workshop Module 05: RAG with Azure AI Search

## Learning Objectives
- Understand how `AzureAISearchContextProvider` enables RAG for agents
- Seed and query the portfolio research knowledge base
- Configure semantic search for improved relevance
- Observe how RAG improves response quality for domain knowledge queries

## AzureAISearchContextProvider

The `AzureAISearchContextProvider` from `agent_framework.azure` automatically injects
relevant search results as context into each agent call. The agent does not need to
call a separate search tool — documents are injected directly into the system prompt.

```python
from agent_framework.azure import AzureAISearchContextProvider
from azure.identity import DefaultAzureCredential

search_provider = AzureAISearchContextProvider(
    endpoint="https://<name>.search.windows.net",
    index_name="portfolio-research",
    credential=DefaultAzureCredential(),
    mode="semantic",               # uses semantic ranking
    query_type="semantic",
    top_k=3,                       # inject top 3 results
)

async with Agent(
    client=client,
    instructions="Answer using the provided research documents.",
    context_providers=[search_provider, history_provider],
) as agent:
    result = await agent.run("What is the AI sector outlook?", session=session)
```

## Seed the Index

If you skipped the post-provision script or want to re-seed:
```bash
cd d:\repos\hackathon
python scripts/seed-search-index.py
```

This uploads 6 synthetic research documents covering:
- AI sector outlook (Technology)
- Federal Reserve rate path (Macroeconomics)
- Financial sector deep dive (Financials)
- Portfolio diversification best practices (Portfolio Management)
- Energy sector transition risks (Energy)
- Healthcare regulatory outlook (Healthcare)

## Exercise 1: Verify RAG injection

Send a query that should match the AI sector research document:
```bash
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the current AI sector outlook?", "session_id": "test-rag"}'
```

The triage agent has `AzureAISearchContextProvider` attached. The response should
reference specific details from the research documents (e.g., "40-60% YoY capex increase").

## Exercise 2: Add your own knowledge document

1. Add a new document to `RESEARCH_DOCS` in `scripts/seed-search-index.py`
2. Re-run: `python scripts/seed-search-index.py`
3. Query the agent about the topic you added

## Exercise 3: Switch to agentic retrieval mode

In `backend/app/workflows/portfolio_workflow.py`, change the search provider `mode`:
```python
# Change from:
mode="semantic"
# To:
mode="agentic"
```

Agentic mode lets the agent reformulate the search query for better recall.
Compare response quality between modes.

## Key Code References
- [backend/app/workflows/portfolio_workflow.py](../../backend/app/workflows/portfolio_workflow.py) — search provider setup
- [scripts/seed-search-index.py](../../scripts/seed-search-index.py) — index seeding

## Next: [Module 06 — Security & Guardrails](./06-security-guardrails.md)
