# Workshop Module 03: Define Your Use-Case & Configure

## Objective

Start building your own application. In this module you will:

1. Copy the clean template into your working directory
2. Decide your use-case and agents
3. Run **Coding Prompt Step 1** through GitHub Copilot to configure settings and scaffolding
4. Verify the blank app skeleton runs

---

## Step 1 — Choose Your Use-Case

Before touching any code you need a clear domain description. Answer these questions:

**What does your app do?** (1–2 sentences)

> Example: "An SME Lending Advisor that helps relationship managers assess credit eligibility,
> check outstanding facility status, and identify covenant compliance risks for small business customers."

**What are 3–5 example questions a user would ask?**

> Example:
> - "What is the current credit limit for customer ABC Corp?"
> - "Are there any covenant breaches on the XYZ facility?"
> - "Is this customer eligible for a £500k working capital facility?"

**What specialist agents will you build?** (typically 3–4)

Think about what DATA SOURCES each agent needs and whether that data is:
- **PUBLIC** — can flow through any agent, no restrictions
- **CONFIDENTIAL** — user or customer-specific; needs row-level security

> Example agents for SME Lending:
> - `credit_eligibility_agent` — PUBLIC + CONFIDENTIAL — checks credit bureau + customer data
> - `facility_status_agent` — CONFIDENTIAL — queries the loan management system (private MCP)
> - `covenant_monitor_agent` — CONFIDENTIAL — checks covenant compliance from financial data
> - `market_risk_agent` — PUBLIC — sector risk signals, industry news

**What are your data sources?**

> Example:
> - Internal loan management system (CONFIDENTIAL → private MCP server)
> - Credit bureau API (public-ish → function tool or external MCP)
> - News and sector data (PUBLIC → Bing Grounding or public API)

Write these down — you will paste them directly into the AI coding prompt below.

---

## Step 2 — Copy the Template

```powershell
cd d:\repos\hackathon

# Create your app directory from the template
Copy-Item -Recurse template\backend my-app\backend
Copy-Item -Recurse template\frontend my-app\frontend
Copy-Item -Recurse template\mcp-servers my-app\mcp-servers

# Copy shared infra and tooling (use as-is)
Copy-Item -Recurse infra my-app\infra
Copy-Item -Recurse scripts my-app\scripts
Copy-Item -Recurse evaluations my-app\evaluations
Copy-Item azure.yaml my-app\
Copy-Item docker-compose.aspire.yml my-app\

cd my-app
```

Review the template structure:

```
my-app/
  backend/
    app/
      core/          <- NEVER MODIFY — auth, observability, sessions, guardrails
      agents/        <- YOUR CODE — one file per specialist agent
      workflows/
        workflow.py  <- YOUR CODE — HandoffBuilder/ConcurrentBuilder wiring
      routes/
        domain.py    <- YOUR CODE — domain-specific REST endpoints
      config.py      <- MODIFY — add your domain settings
      main.py        <- MODIFY — update title, mount your routes
    .env.example     <- MODIFY — document all your env vars
  frontend/
    src/
      components/
        ChatPanel.tsx  <- MODIFY — update example prompts for your domain
        Dashboard.tsx  <- MODIFY — your domain data visualisation
  mcp-servers/
    my-mcp/
      server.py      <- YOUR CODE — private data MCP server
```

---

## Step 3 — Run Coding Prompt Step 1 (Define & Configure)

Open GitHub Copilot Chat in VS Code (agent mode). Paste and fill in the following prompt,
substituting your answers from Step 1:

> The full prompt template is in [template/docs/coding-prompts/README.md](../../template/docs/coding-prompts/README.md) — Step 1.

```
I am building a multi-agent application called "<YOUR APP NAME>" using Microsoft
Agent Framework v1.0.0 and Azure AI Foundry.

The use-case is: <1-2 sentence description>

Example user questions this app should answer:
- <question 1>
- <question 2>
- <question 3>

The app will have these specialist agents:
- <Agent A name>: handles <what it does, what data it uses, PUBLIC or CONFIDENTIAL>
- <Agent B name>: handles <what it does, what data it uses, PUBLIC or CONFIDENTIAL>
- <Agent C name>: handles <what it does, what data it uses, PUBLIC or CONFIDENTIAL>

My data sources are:
- <Source 1>: <description, public or private, how accessed — MCP, function tool, Bing, etc.>
- <Source 2>: <description, public or private, how accessed>

Tasks:
1. Update `my-app/backend/app/config.py`:
   - Rename azure_cosmos_database_name default to match my app
   - Rename azure_search_index_name default to match my app
   - Rename otel_service_name default to my app slug
   - Add domain-specific settings in the DOMAIN-SPECIFIC section:
     one MCP URL per private data source, relevant API key fields,
     and Foundry agent name fields for each specialist agent

2. Update `my-app/backend/app/main.py`:
   - Update the FastAPI title and description to match my app

3. Create `my-app/backend/.env.example` listing all required environment variables
   with placeholder values and a comment explaining each.

4. Update `my-app/frontend/src/components/ChatPanel.tsx`:
   - Replace the PROMPT_GROUPS constant with 3-4 example prompts relevant to my domain
```

Review the changes Copilot makes, then apply them.

---

## Step 4 — Set Up Your Python Environment

```bash
cd my-app\backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd ..\..
```

---

## Step 5 — Create Your .env File

```bash
cd my-app\backend
Copy-Item .env.example .env
```

Fill in the same values from `azd env get-values` that you used for the reference app in Module 02.
The core infrastructure (Foundry, Cosmos DB, AI Search, App Insights) is shared — your app
does not need its own deployment yet.

Add placeholder values for your domain-specific settings (you will fill these in later):

```
# Your domain settings (fill in Module 05 when you build the MCP server)
MY_MCP_URL=http://localhost:8003/mcp
```

---

## Step 6 — Start the Blank App

```bash
cd my-app\backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Expected output includes:

```
INFO:     <YOUR APP NAME> API starting up
INFO:     Foundry endpoint: https://...
INFO:     Application startup complete.
```

Verify the health check:

```bash
Invoke-RestMethod "http://localhost:8000/health"
```

Expected:

```json
{"status": "healthy", "version": "1.0.0", "foundry_endpoint": "https://..."}
```

The app has no domain routes yet — that is expected. The core routes (`/health`, `/api/sessions`)
are already working from `app/core/`.

---

## Verification Checkpoint

- [ ] Template copied into `my-app/`
- [ ] `config.py` has your domain-specific settings
- [ ] `main.py` title matches your app name
- [ ] `.env.example` documents all variables
- [ ] Backend starts without errors and `/health` returns `{"status": "healthy"}`

---

## Next: [Module 04 — Build Specialist Agents & Workflow](./04-mcp-servers.md)
