# Workshop Module 06: RAG, Domain Data & Frontend

## Objective

Add three layers of capability to your application:

1. **RAG via AI Search** — inject domain knowledge into agent context on every call
2. **Domain data REST endpoints** — power the dashboard with real data from your backend
3. **Frontend customisation** — update the React SPA to match your use-case

By the end the app will feel like it was built for your domain, not a generic template.

---

## Part A: RAG with Azure AI Search

### How it works

`AzureAISearchContextProvider` from `agent_framework.azure` runs a search query against your
AI Search index on every agent invocation and injects the top matching documents directly
into the agent's system context. The agent sees this as background knowledge — it does not
need to call a search tool explicitly.

```
User message: "What are the current risks in the SME lending sector?"
                      |
         AzureAISearchContextProvider
         runs: index.search("SME lending risks")
         injects: top 3 matching research documents
                      |
         Agent receives: system context + injected docs + user message
         Agent response: grounded in your knowledge base
```

### Step 1 — Create Your Domain Research Documents

Edit `scripts/seed-search-index.py`. Replace the portfolio research documents with
documents relevant to your domain.

Each document should be:
- 300–800 words of dense domain knowledge
- Focused on one specific topic (not a scatter of topics)
- The kind of background information your agents need to give expert-level answers

```python
# Example structure in seed-search-index.py
RESEARCH_DOCS = [
    {
        "id": "doc-001",
        "title": "SME Credit Risk Assessment Framework",
        "content": """
            ... 400-700 words of domain knowledge ...
        """,
        "category": "credit-risk",
        "source": "internal-guidelines",
    },
    # Add 5-8 documents covering your key domain topics
]
```

Aim for **6–10 documents** covering the most common knowledge gaps your agents will face.

### Step 2 — Seed Your Search Index

```bash
cd d:\repos\hackathon

# Update the index name to match your config
python scripts/seed-search-index.py --index-name <your-azure-search-index-name>
```

Verify the index was seeded:

```powershell
$searchEndpoint = azd env get-value AZURE_SEARCH_ENDPOINT
$token = (az account get-access-token --resource "https://search.azure.com" | ConvertFrom-Json).accessToken
Invoke-RestMethod `
    -Uri "$searchEndpoint/indexes/<your-index>/docs?api-version=2023-11-01&search=*&`$count=true" `
    -Headers @{ "Authorization"="Bearer $token" }
```

Expected: `@odata.count` matches the number of documents you seeded.

### Step 3 — Attach Search Provider to Agents

In `my-app/backend/app/workflows/workflow.py`, inside `build_specialist_agents()` (or in your
specific agent files), attach the search provider to agents that benefit from domain knowledge:

```python
from agent_framework.azure import AzureAISearchContextProvider
from azure.identity import DefaultAzureCredential

search_provider = AzureAISearchContextProvider(
    endpoint=settings.azure_search_endpoint,
    index_name=settings.azure_search_index_name,
    credential=DefaultAzureCredential(),
    mode="semantic",    # use "agentic" for better multi-hop retrieval
    top_k=3,
)
```

Attach it to agents that need background knowledge:

```python
agent = Agent(
    client=client,
    name="my_agent",
    instructions=INSTRUCTIONS,
    tools=[...],
    context_providers=[history_provider, search_provider, compaction_provider],
    require_per_service_call_history_persistence=True,
)
```

**Note**: Attach search providers only to agents where domain knowledge adds value.
Agents that only call real-time data APIs (quotes, live status) generally do not benefit.

### Step 4 — Verify RAG Injection

Ask a question that matches one of your seeded documents:

```powershell
$body = @{
    message = "<question that should match a seeded document>"
    session_id = "test-rag-01"
} | ConvertTo-Json

Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8000/api/chat/message" `
    -ContentType "application/json" `
    -Body $body
```

The response should contain specific facts or figures from your seeded documents —
if the response is generic and could have been generated without your documents, the
search is not matching or the content is too thin.

---

## Part B: Domain Data REST Endpoints

The dashboard component in the frontend needs data from your backend to display
domain-specific metrics (holdings table, risk chart, facility summary, etc.).

### Step 1 — Run Coding Prompt Step 6 (Domain Data Endpoints)

> Full prompt in [template/docs/coding-prompts/README.md](../../template/docs/coding-prompts/README.md) — Step 6.

```
I need to add domain-specific REST API endpoints to my application "<YOUR APP NAME>".

The frontend Dashboard component needs the following data:

Endpoint 1: GET /api/domain/<resource-1>
  - Returns: <describe the response shape — list of objects, a summary dict, etc.>
  - Auth: <does it need the user's identity to filter data? yes/no>
  - Data source: <where does this data come from — your MCP, Cosmos DB, etc.>

Endpoint 2: GET /api/domain/<resource-2>
  - Returns: <describe the response shape>
  - Auth: <yes/no>
  - Data source: <source>

Add these endpoints to `my-app/backend/app/routes/domain.py`.
Use `DefaultAzureCredential()` for any Azure service calls.
If auth is needed, use `require_authenticated_user` from `app.core.auth.middleware`.
Return empty lists (not 404) when no data is found for the authenticated user.
```

### Step 2 — Test Domain Endpoints

```bash
# Test without auth (local dev mode)
Invoke-RestMethod "http://localhost:8000/api/domain/<resource-1>"
```

---

## Part C: Frontend Customisation

### Step 1 — Run Coding Prompt Step 7 (Frontend)

> Full prompt in [template/docs/coding-prompts/README.md](../../template/docs/coding-prompts/README.md) — Step 7.

```
I need to customise the React frontend for my application "<YOUR APP NAME>".

1. Update `my-app/frontend/src/components/ChatPanel.tsx`:
   Replace the PROMPT_GROUPS constant with groups relevant to my domain:
   Group 1: "<group label>" with prompts:
     - "<example prompt 1>"
     - "<example prompt 2>"
   Group 2: "<group label>" with prompts:
     - "<example prompt 3>"
     - "<example prompt 4>"

2. Update `my-app/frontend/src/components/Dashboard.tsx`:
   Replace the portfolio holdings table and charts with components relevant to my domain.
   The dashboard should fetch data from GET /api/domain/<resource-1> and display it as
   <describe the visual: a table, a bar chart, a status grid, etc.>.
   Use the existing Recharts imports and Tailwind CSS classes — do not add new libraries.
   Show a loading skeleton while data is loading and an error state if the API fails.

3. Update `my-app/frontend/src/components/NavBar.tsx`:
   Change the app name/title in the nav bar to "<YOUR APP NAME>".

Keep the core layout (NavBar, ChatPanel, Dashboard side-by-side) unchanged.
Do not modify any files under src/hooks/ or the authentication flow.
```

### Step 2 — Start the Frontend

```bash
cd my-app\frontend
npm install
npm run dev
# http://localhost:5173
```

Open [http://localhost:5173](http://localhost:5173). You should see your app name, your
domain-specific example prompts in the sidebar, and your dashboard layout.

---

## Verification Checkpoint

**RAG**:
- [ ] `scripts/seed-search-index.py` updated with your domain documents (6-10 docs)
- [ ] AI Search index seeded and document count confirmed
- [ ] Agent response to a domain question contains facts from your seeded documents

**Domain Endpoints**:
- [ ] `GET /api/domain/<resource>` returns structured data
- [ ] Response matches the shape expected by the frontend Dashboard component

**Frontend**:
- [ ] App name updated in NavBar
- [ ] Example prompts are domain-relevant
- [ ] Dashboard shows real data (not hardcoded)
- [ ] Loading and error states work

---

## Next: [Module 07 — Security, Guardrails & Deployment](./07-compaction.md)
