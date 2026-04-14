import { useState, useEffect, useRef } from 'react'
import { useMsal } from '@azure/msal-react'
import { loginRequest, tokenRequest } from '../authConfig'

// =========================================================================
// AuthFlowPanel
// Security visualization for each agent response.
// Shows: auth pattern, end-to-end token flow, live JWT claims from MSAL,
// OBO token transformation, MCP validation steps, and key security props.
// Intended for security / InfoSec review of the multi-agent auth design.
// =========================================================================

// --- Types ---

type NodeType =
  | 'browser' | 'backend' | 'entra' | 'obo'
  | 'mcp-private' | 'mcp-public' | 'external'
  | 'data' | 'foundry' | 'a2a' | 'github' | 'cosmos'

type CredentialType =
  | 'entra-jwt' | 'obo-portfolio' | 'obo-market'
  | 'api-key' | 'github-oauth' | 'managed-identity'
  | 'json-rpc' | 'none' | 'internal'
  | 'mock-oidc' | 'client-creds'

type PatternKey = '1a' | '1b' | '2' | 'foundry' | 'a2a' | 'concurrent' | 'handoff' | 'multi-idp' | 'okta-proxy'
type SecurityLevel = 'PUBLIC' | 'CONFIDENTIAL' | 'INTERNAL'

interface FlowStep {
  nodeType: NodeType
  title: string
  subtitle: string
  detail: string
  fileRef: string
}

interface FlowArrow {
  credential: CredentialType
  label: string
}

interface FlowDef {
  pattern: PatternKey
  patternLabel: string
  securityLevel: SecurityLevel
  description: string
  highlightOBO: boolean
  steps: FlowStep[]
  arrows: FlowArrow[]
  observations: string[]
}

// --- Complete Tailwind class lookup (no dynamic class construction) ---

const NODE_STYLES: Record<NodeType, {
  border: string; headerBg: string; icon: string; title: string; ring: string
}> = {
  'browser':     { border: 'border-indigo-500/50', headerBg: 'bg-indigo-600/15', icon: 'text-indigo-400', title: 'text-indigo-200', ring: 'ring-indigo-500/20' },
  'backend':     { border: 'border-slate-500/50',  headerBg: 'bg-slate-600/15',  icon: 'text-slate-400',  title: 'text-slate-200',  ring: 'ring-slate-500/20'  },
  'entra':       { border: 'border-sky-500/50',    headerBg: 'bg-sky-600/15',    icon: 'text-sky-400',    title: 'text-sky-200',    ring: 'ring-sky-500/20'    },
  'obo':         { border: 'border-amber-500/50',  headerBg: 'bg-amber-600/15',  icon: 'text-amber-400',  title: 'text-amber-200',  ring: 'ring-amber-500/20'  },
  'mcp-private': { border: 'border-emerald-500/50',headerBg: 'bg-emerald-600/15',icon: 'text-emerald-400',title: 'text-emerald-200',ring: 'ring-emerald-500/20'},
  'mcp-public':  { border: 'border-purple-500/50', headerBg: 'bg-purple-600/15', icon: 'text-purple-400', title: 'text-purple-200', ring: 'ring-purple-500/20' },
  'external':    { border: 'border-teal-500/50',   headerBg: 'bg-teal-600/15',   icon: 'text-teal-400',   title: 'text-teal-200',   ring: 'ring-teal-500/20'   },
  'data':        { border: 'border-blue-500/50',   headerBg: 'bg-blue-600/15',   icon: 'text-blue-400',   title: 'text-blue-200',   ring: 'ring-blue-500/20'   },
  'foundry':     { border: 'border-violet-500/50', headerBg: 'bg-violet-600/15', icon: 'text-violet-400', title: 'text-violet-200', ring: 'ring-violet-500/20' },
  'a2a':         { border: 'border-lime-500/50',   headerBg: 'bg-lime-600/15',   icon: 'text-lime-400',   title: 'text-lime-200',   ring: 'ring-lime-500/20'   },
  'github':      { border: 'border-gray-400/50',   headerBg: 'bg-gray-600/15',   icon: 'text-gray-400',   title: 'text-gray-200',   ring: 'ring-gray-500/20'   },
  'cosmos':      { border: 'border-cyan-500/50',   headerBg: 'bg-cyan-600/15',   icon: 'text-cyan-400',   title: 'text-cyan-200',   ring: 'ring-cyan-500/20'   },
}

const CRED_STYLES: Record<CredentialType, { bg: string; text: string; ring: string }> = {
  'entra-jwt':        { bg: 'bg-sky-950',    text: 'text-sky-300',    ring: 'ring-sky-700/50'    },
  'obo-portfolio':    { bg: 'bg-amber-950',  text: 'text-amber-300',  ring: 'ring-amber-700/50'  },
  'obo-market':       { bg: 'bg-amber-950',  text: 'text-amber-300',  ring: 'ring-amber-700/50'  },
  'api-key':          { bg: 'bg-yellow-950', text: 'text-yellow-300', ring: 'ring-yellow-700/50' },
  'github-oauth':     { bg: 'bg-gray-800',   text: 'text-gray-300',   ring: 'ring-gray-600/50'   },
  'managed-identity': { bg: 'bg-violet-950', text: 'text-violet-300', ring: 'ring-violet-700/50' },
  'json-rpc':         { bg: 'bg-lime-950',   text: 'text-lime-300',   ring: 'ring-lime-700/50'   },
  'none':             { bg: 'bg-gray-900',   text: 'text-gray-500',   ring: 'ring-gray-700/50'   },
  'internal':         { bg: 'bg-gray-900',   text: 'text-gray-400',   ring: 'ring-gray-600/50'   },
  'mock-oidc':        { bg: 'bg-orange-950', text: 'text-orange-300', ring: 'ring-orange-700/50' },
  'client-creds':     { bg: 'bg-violet-950', text: 'text-violet-300', ring: 'ring-violet-700/50' },
}

const SEC_STYLES: Record<SecurityLevel, { bg: string; text: string; ring: string; dot: string }> = {
  PUBLIC:       { bg: 'bg-green-950',  text: 'text-green-300',  ring: 'ring-green-700/50',  dot: 'bg-green-400' },
  CONFIDENTIAL: { bg: 'bg-red-950',    text: 'text-red-300',    ring: 'ring-red-700/50',    dot: 'bg-red-400'   },
  INTERNAL:     { bg: 'bg-orange-950', text: 'text-orange-300', ring: 'ring-orange-700/50', dot: 'bg-orange-400'},
}

const PATTERN_STYLES: Record<PatternKey, { bg: string; text: string; ring: string }> = {
  '1a':        { bg: 'bg-emerald-950', text: 'text-emerald-300', ring: 'ring-emerald-700/50' },
  '1b':        { bg: 'bg-yellow-950',  text: 'text-yellow-300',  ring: 'ring-yellow-700/50'  },
  '2':         { bg: 'bg-teal-950',    text: 'text-teal-300',    ring: 'ring-teal-700/50'    },
  'foundry':   { bg: 'bg-violet-950',  text: 'text-violet-300',  ring: 'ring-violet-700/50'  },
  'a2a':       { bg: 'bg-lime-950',    text: 'text-lime-300',    ring: 'ring-lime-700/50'    },
  'concurrent':{ bg: 'bg-rose-950',    text: 'text-rose-300',    ring: 'ring-rose-700/50'    },
  'handoff':   { bg: 'bg-indigo-950',  text: 'text-indigo-300',  ring: 'ring-indigo-700/50'  },
  'multi-idp': { bg: 'bg-orange-950',  text: 'text-orange-300',  ring: 'ring-orange-700/50'  },
  'okta-proxy':{ bg: 'bg-rose-950',    text: 'text-rose-300',    ring: 'ring-rose-700/50'    },
}

// --- Flow definitions per agent ---

const FLOWS: Record<string, FlowDef> = {

  economic_agent: {
    pattern: '1b',
    patternLabel: 'Pattern 1b: External Public MCP + Backend API Key',
    securityLevel: 'PUBLIC',
    description: 'Alpha Vantage MCP is a remote SaaS endpoint. No user identity is propagated — this agent only returns public economic data. Auth uses a backend-held API key stored in Key Vault, injected via environment variable.',
    highlightOBO: false,
    steps: [
      {
        nodeType: 'browser',
        title: 'Browser / SPA',
        subtitle: 'No auth required',
        detail: 'Economic data is public — no Entra token needed. If a user is signed in, a dev identity is used. MSAL login is optional for this agent.',
        fileRef: 'frontend/src/authConfig.ts',
      },
      {
        nodeType: 'backend',
        title: 'FastAPI Backend',
        subtitle: 'Guardrail + triage routing',
        detail: 'check_user_message() runs content policy. Triage agent routes to economic_agent matching "Economic data, interest rates, Fed policy, yield curve, GDP, inflation".',
        fileRef: 'backend/app/core/auth/middleware.py',
      },
      {
        nodeType: 'external',
        title: 'EconomicDataAgent',
        subtitle: 'Builds MCPTool or FunctionTool',
        detail: 'API key loaded from ALPHAVANTAGE_API_KEY env var (injected from Key Vault). If key is present: MCPStreamableHTTPTool. If absent: FunctionTool REST fallback. Key is a backend-only secret, never exposed to the browser.',
        fileRef: 'backend/app/agents/economic_data.py:build_tools',
      },
      {
        nodeType: 'external',
        title: 'Alpha Vantage MCP',
        subtitle: 'Remote SaaS — mcp.alphavantage.co',
        detail: 'Publicly hosted MCP endpoint. API key in URL param (?apikey=). Tools: get_federal_funds_rate, get_treasury_yield, get_cpi, get_inflation, get_real_gdp, get_wti_crude. INTERVAL_MAX_POINTS caps data before passing to LLM.',
        fileRef: 'backend/app/agents/economic_data.py:INTERVAL_MAX_POINTS',
      },
      {
        nodeType: 'data',
        title: 'Economic Data',
        subtitle: 'Fed, GDP, CPI, FX, Commodities',
        detail: 'Returns time-series JSON truncated to context-safe window (e.g. 30 daily pts, 24 monthly pts). Agent cites observation_date on every data point. Data classification: PUBLIC.',
        fileRef: 'backend/app/agents/economic_data.py:_fetch',
      },
    ],
    arrows: [
      { credential: 'none',    label: 'No token (public data)' },
      { credential: 'none',    label: 'Dev identity only' },
      { credential: 'api-key', label: 'API key from Key Vault env' },
      { credential: 'api-key', label: '?apikey=<secret> in URL' },
    ],
    observations: [
      'API key is a backend secret — Key Vault reference, never in client code or browser response.',
      'No user identity is propagated because Alpha Vantage serves only public data.',
      'FunctionTool fallback means the agent works in local dev without the remote MCP endpoint.',
    ],
  },

  market_intel_agent: {
    pattern: 'foundry',
    patternLabel: 'Foundry Prompt Agent + Managed Identity + Bing Grounding',
    securityLevel: 'PUBLIC',
    description: 'Market Intel is a pre-configured Azure AI Foundry Prompt Agent with Bing Grounding baked in server-side. The backend authenticates to Foundry via Managed Identity. No API key or user token is forwarded to Bing — the grounding connection is Foundry-managed.',
    highlightOBO: false,
    steps: [
      {
        nodeType: 'browser',
        title: 'Browser / SPA',
        subtitle: 'Optional Entra token',
        detail: 'Market news is public. MSAL token is optional. If signed in, token is validated by backend but not forwarded to Bing.',
        fileRef: 'frontend/src/authConfig.ts',
      },
      {
        nodeType: 'backend',
        title: 'FastAPI Backend',
        subtitle: 'RS256 JWKS validation',
        detail: 'EntraJWTValidator (RS256, JWKS cached by kid) validates token if present. AuthContext extracted. Triage agent matches "Market news, stock analysis, earnings, sector trends, analyst ratings" -> market_intel_agent.',
        fileRef: 'backend/app/core/auth/middleware.py:EntraJWTValidator',
      },
      {
        nodeType: 'foundry',
        title: 'MarketIntelAgent',
        subtitle: 'RawFoundryAgentChatClient',
        detail: 'Uses RawFoundryAgentChatClient (not shared FoundryChatClient) because Bing Grounding is a server-side hosted tool — it must be defined in the Foundry portal, not injected at call time. Agent name: "portfolio-market-intel".',
        fileRef: 'backend/app/agents/market_intel.py:MarketIntelAgent.create',
      },
      {
        nodeType: 'foundry',
        title: 'Azure AI Foundry',
        subtitle: 'Agents Service — Managed Identity',
        detail: 'DefaultAzureCredential -> Managed Identity authenticates the backend Container App to Foundry. No client secret needed. Foundry looks up the "portfolio-market-intel" agent definition and activates its Bing Grounding connection.',
        fileRef: 'infra/modules/foundry.bicep + infra/modules/managed-identity.bicep',
      },
      {
        nodeType: 'external',
        title: 'Bing Search',
        subtitle: 'Real-time web grounding',
        detail: 'Foundry uses a project-level connection to Bing Search. Returns cited sources with name + date + URL. System prompt mandates citing sources and flagging stale data.',
        fileRef: 'backend/app/agents/market_intel.py:MARKET_INTEL_INSTRUCTIONS',
      },
    ],
    arrows: [
      { credential: 'entra-jwt',        label: 'Bearer Entra JWT (optional)' },
      { credential: 'entra-jwt',        label: 'Validated AuthContext' },
      { credential: 'managed-identity', label: 'DefaultAzureCredential (MI)' },
      { credential: 'managed-identity', label: 'Foundry-managed MI connection' },
    ],
    observations: [
      'Managed Identity eliminates any API key rotation burden — Azure handles the credential lifecycle.',
      'Bing Grounding is server-side only: the tool is attached to the Foundry agent definition, not injected at request time.',
      'System prompt explicitly bans accessing portfolio positions, enforcing the PUBLIC data boundary.',
    ],
  },

  portfolio_agent: {
    pattern: '1a',
    patternLabel: 'Pattern 1a: Private MCP + Entra OBO (On-Behalf-Of)',
    securityLevel: 'CONFIDENTIAL',
    description: 'The most secure pattern. User identity flows end-to-end via the Entra On-Behalf-Of grant. The backend exchanges the user\'s Entra token for an audience-scoped OBO token. Portfolio MCP performs full JWKS validation + scope check + SQL row-level security on every single tool call.',
    highlightOBO: true,
    steps: [
      {
        nodeType: 'browser',
        title: 'Browser (MSAL)',
        subtitle: 'Entra token REQUIRED',
        detail: 'MSAL acquireTokenSilent() fetches access token with scope: api://<BACKEND_CLIENT_ID>/Chat.Read. Token audience = backend API app registration only. The token is opaque to the frontend.',
        fileRef: 'frontend/src/authConfig.ts:loginRequest',
      },
      {
        nodeType: 'backend',
        title: 'FastAPI Backend',
        subtitle: 'RS256 JWKS + AuthContext',
        detail: 'EntraJWTValidator: GET JWKS from Entra (cached; kid mismatch triggers re-fetch for key rotation). RS256 verify: aud=ENTRA_BACKEND_CLIENT_ID, iss=login.microsoftonline.com/{tenant}/v2.0, exp checked. Returns AuthContext {claims, raw_token}.',
        fileRef: 'backend/app/core/auth/middleware.py:require_auth_context',
      },
      {
        nodeType: 'obo',
        title: 'OBO Exchange',
        subtitle: 'OnBehalfOfCredential at Entra /token',
        detail: 'OBOAuth.async_auth_flow: POST /oauth2/v2.0/token with grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer, user_assertion=<raw_token>. PRODUCES new token: aud=api://<PORTFOLIO_MCP_CLIENT_ID>, scp=portfolio.read, oid=PRESERVED. Token cached; auto-refreshes on HTTP 401.',
        fileRef: 'backend/app/core/auth/obo.py:OBOAuth',
      },
      {
        nodeType: 'mcp-private',
        title: 'Portfolio DB MCP',
        subtitle: 'Internal Container App (external:false)',
        detail: 'Not reachable from public internet. EntraTokenVerifier: JWKS validate OBO token. check_scope("portfolio.read") on every tool call. get_user_id_from_request() extracts oid / preferred_username from validated claims.',
        fileRef: 'mcp-servers/portfolio-db/entra_auth.py:EntraTokenVerifier',
      },
      {
        nodeType: 'data',
        title: 'SQLite / Fabric',
        subtitle: 'SQL Row-Level Security',
        detail: 'SELECT * FROM holdings WHERE user_id = ? (parameterized). oid from OBO token is the parameter. Even if the application layer were compromised, the SQL filter enforces per-user isolation at the data layer.',
        fileRef: 'mcp-servers/portfolio-db/server.py:_db_get_holdings',
      },
    ],
    arrows: [
      { credential: 'entra-jwt',     label: 'Bearer Entra JWT (aud=backend)' },
      { credential: 'entra-jwt',     label: 'raw_token threaded to build_tools()' },
      { credential: 'obo-portfolio', label: 'OBO Token (aud=portfolio-mcp, scp=portfolio.read)' },
      { credential: 'obo-portfolio', label: 'JWKS validated + scope checked + oid extracted' },
    ],
    observations: [
      'OBO preserves oid across the trust boundary — the MCP server sees the real user identity, not a service identity.',
      'Token audience is isolated: the OBO token is only accepted by portfolio-db MCP; no other service can use it.',
      'Row-level security at SQL layer provides defense-in-depth — data isolation holds even if the MCP layer is bypassed.',
    ],
  },

  private_data_agent: {
    pattern: '1a',
    patternLabel: 'Pattern 1a: Private MCP + Entra OBO (scope: market.read)',
    securityLevel: 'PUBLIC',
    description: 'Same OBO architecture as Portfolio Data but with market.read scope targeting the Yahoo Finance MCP. Public market data means no row-level security is required, but the OBO token still enforces that only authorized backends can call the MCP and creates a per-user audit trail.',
    highlightOBO: true,
    steps: [
      {
        nodeType: 'browser',
        title: 'Browser (MSAL)',
        subtitle: 'Optional Entra token',
        detail: 'Market data is public. MSAL acquires token if signed in. Token is forwarded for audit trail purposes — each yfinance call is attributed to a specific user oid in the audit log.',
        fileRef: 'frontend/src/authConfig.ts',
      },
      {
        nodeType: 'backend',
        title: 'FastAPI Backend',
        subtitle: 'RS256 JWKS validation',
        detail: 'EntraJWTValidator validates token. raw_token is threaded through orchestrator -> build_specialist_agents() -> PrivateDataAgent.build_tools(raw_token=...) -> build_obo_http_client().',
        fileRef: 'backend/app/core/auth/middleware.py',
      },
      {
        nodeType: 'obo',
        title: 'OBO Exchange',
        subtitle: 'scope: market.read',
        detail: 'OnBehalfOfCredential: same user assertion (raw_token) as portfolio OBO, but different scope and target. New OBO token: aud=api://<YAHOO_MCP_CLIENT_ID>, scp=market.read, oid preserved for audit trail.',
        fileRef: 'backend/app/core/auth/obo.py:build_obo_http_client',
      },
      {
        nodeType: 'mcp-public',
        title: 'Yahoo Finance MCP',
        subtitle: 'Internal Container App (external:false)',
        detail: 'Not reachable from public internet. EntraTokenVerifier validates OBO token. check_scope("market.read"). audit_log() records caller_id (oid), tool name, duration_ms, outcome on every call. get_caller_id() for logging only (no RLS needed for public data).',
        fileRef: 'mcp-servers/yahoo-finance/entra_auth.py + server.py:audit_log',
      },
      {
        nodeType: 'data',
        title: 'yfinance / Yahoo Finance',
        subtitle: 'Public market data',
        detail: 'yf.Ticker(symbol).fast_info for quotes. yf.Ticker(symbol).info for fundamentals. _validate_symbol() regex (^[A-Z0-9.\\-\\^=]{1,10}$) validates all inputs before API call. lru_cache on expensive calls.',
        fileRef: 'mcp-servers/yahoo-finance/server.py:_validate_symbol',
      },
    ],
    arrows: [
      { credential: 'entra-jwt',  label: 'Bearer Entra JWT (optional, for audit)' },
      { credential: 'entra-jwt',  label: 'raw_token threaded to build_tools()' },
      { credential: 'obo-market', label: 'OBO Token (aud=yahoo-mcp, scp=market.read)' },
      { credential: 'obo-market', label: 'JWKS validated + per-call audit_log()' },
    ],
    observations: [
      'Even for public data, OBO enforces that only the authorized backend service can reach Yahoo Finance MCP.',
      'audit_log() creates a per-user, per-tool-call record in Application Insights for forensic review.',
      'Input validation (regex allowlist) at the MCP boundary prevents injection attacks before any downstream API call.',
    ],
  },

  github_intel_agent: {
    pattern: '2',
    patternLabel: 'Pattern 2: External Vendor MCP + Per-User GitHub OAuth',
    securityLevel: 'PUBLIC',
    description: 'GitHub uses its own OAuth identity system — Entra tokens are never accepted. Users authorize a GitHub OAuth App once; the access token is stored server-side in Cosmos DB keyed by the user\'s Entra oid. A stateless HMAC-signed state prevents CSRF during the OAuth flow.',
    highlightOBO: false,
    steps: [
      {
        nodeType: 'browser',
        title: 'GitHub Connect (one-time)',
        subtitle: 'OAuth Authorization Code flow',
        detail: 'User clicks "Connect GitHub". GET /api/auth/github with Entra Bearer. Backend builds HMAC-signed state={oid, timestamp}. 302 redirect to github.com/login/oauth/authorize?scope=public_repo+read:user&state=<hmac>.',
        fileRef: 'frontend/src/components/NavBar.tsx:handleGitHubConnect',
      },
      {
        nodeType: 'entra',
        title: 'CSRF Protection',
        subtitle: 'HMAC-SHA256 stateless state',
        detail: '_make_state(): state = hex(JSON{oid,ts}).HMAC-SHA256(secret). _verify_state(): hmac.compare_digest() prevents timing attack. 10-min expiry window closes replay attacks. oid recovered from state payload — no server session required.',
        fileRef: 'backend/app/routes/github_auth.py:_make_state / _verify_state',
      },
      {
        nodeType: 'github',
        title: 'GitHub OAuth Callback',
        subtitle: 'Code -> access_token exchange',
        detail: 'GET /api/auth/github/callback?code=<code>&state=<hmac>. Verify HMAC state. POST github.com/login/oauth/access_token with client_id, client_secret (Key Vault), code. Returns {access_token, scope: "public_repo read:user"}.',
        fileRef: 'backend/app/routes/github_auth.py:github_callback',
      },
      {
        nodeType: 'cosmos',
        title: 'Cosmos DB Token Store',
        subtitle: 'vendor-oauth-tokens container',
        detail: 'Document: {id: "<oid>-github", user_oid, vendor, access_token, stored_at}. Partition key: /user_oid. Upsert is idempotent — re-auth replaces doc. Retrieved in run_handoff() BEFORE build_specialist_agents() (async/sync boundary pattern).',
        fileRef: 'backend/app/core/auth/vendor_oauth_store.py:GitHubTokenStore',
      },
      {
        nodeType: 'external',
        title: 'GitHub REST API',
        subtitle: 'Engineering metrics',
        detail: 'Authorization: Bearer <github_token>. Uses Search API (/search/repositories) not (/orgs/) to avoid OAuth App org restrictions. Tools: get_org_repos, get_repo_commits, get_repo_stats, get_repo_issues. 5,000 req/hr when authenticated.',
        fileRef: 'backend/app/agents/github_intel.py:_build_github_rest_tools',
      },
    ],
    arrows: [
      { credential: 'entra-jwt',    label: 'Entra JWT identifies user oid for state' },
      { credential: 'github-oauth', label: 'HMAC-signed state + auth code' },
      { credential: 'github-oauth', label: 'GitHub access_token (per user, scoped)' },
      { credential: 'github-oauth', label: 'Retrieved from Cosmos by oid' },
    ],
    observations: [
      'GitHub token is stored server-side — it never touches the browser after the OAuth redirect.',
      'HMAC-signed state eliminates the need for server-side session storage during the OAuth flow (stateless backend).',
      'Graceful degradation: if no token exists, a FunctionTool stub returns a connect-prompt instead of throwing an error.',
    ],
  },

  esg_advisor_agent: {
    pattern: 'a2a',
    patternLabel: 'A2A Protocol: Agent-to-Agent (LangChain ReAct remote server)',
    securityLevel: 'PUBLIC',
    description: 'ESG analysis requires a full multi-tool reasoning loop, not a single function call. A remote LangChain ReAct agent is delegated the entire ESG query via the Agent-to-Agent (A2A) JSON-RPC protocol. The backend wraps this in a FunctionTool so HandoffBuilder can route to it like any other specialist.',
    highlightOBO: false,
    steps: [
      {
        nodeType: 'browser',
        title: 'Browser / SPA',
        subtitle: 'No special auth required',
        detail: 'ESG governance scores are public. Authentication is optional. The agent is skipped entirely if ESG_ADVISOR_URL is not configured (create_from_context returns None).',
        fileRef: 'frontend/src/components/ChatPanel.tsx:PROMPT_GROUPS',
      },
      {
        nodeType: 'backend',
        title: 'ESGAdvisorAgent',
        subtitle: 'Wraps A2A call as FunctionTool',
        detail: 'HandoffBuilder requires Agent instances (not A2AAgent). ESGAdvisorAgent creates a regular Agent with a single query_esg_advisor() FunctionTool. When the LLM calls that tool, the A2A transport activates. Returns None if ESG_ADVISOR_URL unset.',
        fileRef: 'backend/app/agents/esg_advisor.py:ESGAdvisorAgent',
      },
      {
        nodeType: 'a2a',
        title: 'A2A Transport',
        subtitle: 'JSON-RPC 2.0 POST /',
        detail: 'A2AAgent(url=esg_advisor_url). First call: GET /.well-known/agent.json -> AgentCard (capability discovery). Then POST / with {jsonrpc:"2.0", method:"tasks/send", params:{message}}. Awaits TaskStatusUpdateEvent + TaskArtifactUpdateEvent stream.',
        fileRef: 'backend/app/agents/esg_advisor.py:_make_query_esg_tool',
      },
      {
        nodeType: 'a2a',
        title: 'ESG A2A Server',
        subtitle: 'LangChain ReAct full reasoning loop',
        detail: 'Receives JSON-RPC task. ReAct loop: think -> call get_esg_scores() or get_esg_peer_comparison() or get_controversy_analysis() -> observe -> repeat. LangChain synthesizes across all tool results. Supports Azure OpenAI or OpenAI as LLM backend.',
        fileRef: 'a2a-agents/esg-advisor/server.py',
      },
      {
        nodeType: 'data',
        title: 'ISS Governance Scores',
        subtitle: 'yfinance info endpoint',
        detail: 'yf.Ticker(t).info -> auditRisk, boardRisk, compensationRisk, shareHolderRightsRisk, overallRisk (1-10, lower=better). Flags any dimension >=7 as high-risk. Note: Yahoo Finance removed Sustainalytics data in 2025; ISS scores are the available proxy.',
        fileRef: 'a2a-agents/esg-advisor/server.py:_fetch_governance',
      },
    ],
    arrows: [
      { credential: 'none',     label: 'No token (public ESG data)' },
      { credential: 'internal', label: 'LLM calls FunctionTool' },
      { credential: 'json-rpc', label: 'A2A JSON-RPC POST / (internal network)' },
      { credential: 'internal', label: 'ReAct tool calls -> yfinance' },
    ],
    observations: [
      'A2A delegates a full reasoning loop to a different agent runtime (LangChain vs Agent Framework) — heterogeneous AI orchestration.',
      'AgentCard capability discovery (/.well-known/agent.json) provides explicit contract negotiation between caller and callee.',
      'The wrapper pattern (FunctionTool over A2A) satisfies HandoffBuilder\'s Agent type requirement without modifying the framework.',
    ],
  },

  synthesis: {
    pattern: 'concurrent',
    patternLabel: 'ConcurrentBuilder: All agents in parallel + Synthesis',
    securityLevel: 'CONFIDENTIAL',
    description: 'All specialist agents run concurrently. Each uses its own independent auth pattern. The synthesis agent receives all outputs as conversation history (no tools of its own) and produces a structured 6-section investment advisory report.',
    highlightOBO: false,
    steps: [
      {
        nodeType: 'backend',
        title: 'ConcurrentBuilder',
        subtitle: 'Fan-out: all agents in parallel',
        detail: 'run_comprehensive() triggers ConcurrentBuilder. All specialists run concurrently as async tasks: economic_agent + market_intel_agent + portfolio_agent + private_data_agent + github_intel_agent + esg_advisor_agent. Total latency = max(latencies), not sum.',
        fileRef: 'backend/app/core/workflows/base.py:BaseOrchestrator.run_comprehensive',
      },
      {
        nodeType: 'obo',
        title: 'Parallel OBO Tokens',
        subtitle: 'Independent per-service',
        detail: 'Single raw_token used as assertion for BOTH OBO exchanges concurrently. OBO for portfolio.read and OBO for market.read execute independently. Tokens are NEVER shared between MCP servers. Each produces a distinct audience-scoped token.',
        fileRef: 'backend/app/core/auth/obo.py:OBOAuth.async_auth_flow',
      },
      {
        nodeType: 'mcp-private',
        title: 'All Specialists Complete',
        subtitle: '6 agents x their own auth patterns',
        detail: 'Economic (API key) + Market Intel (MI) + Portfolio (OBO portfolio.read + RLS) + Private Data (OBO market.read) + GitHub (per-user OAuth) + ESG (A2A). Each agent runs its full tool loop. CompactionProvider manages context budget.',
        fileRef: 'backend/app/workflows/portfolio_workflow.py:build_specialist_agents',
      },
      {
        nodeType: 'foundry',
        title: 'Synthesis Agent',
        subtitle: 'Reasoning only — no tools',
        detail: 'Receives all 6 specialist outputs as conversation context. Produces: 1) Portfolio Snapshot, 2) Market Context, 3) Macro Environment, 4) ESG & Sustainability Profile, 5) Key Risks and Opportunities, 6) Actionable Recommendations. Cannot call tools — eliminates accidental data exfiltration during synthesis.',
        fileRef: 'backend/app/workflows/portfolio_workflow.py:build_synthesis_agent',
      },
      {
        nodeType: 'cosmos',
        title: 'Cosmos DB Persistence',
        subtitle: 'Session + compaction',
        detail: 'Full session persisted to chat-sessions container. azure_cosmos_checkpoints_container stores workflow state for resume on failure. TokenBudgetComposedStrategy (100K char budget) + SlidingWindowStrategy (keep last 20 groups) prevents context overflow on long sessions.',
        fileRef: 'backend/app/core/workflows/base.py:_get_compaction_provider',
      },
    ],
    arrows: [
      { credential: 'obo-portfolio', label: 'All auth patterns triggered in parallel' },
      { credential: 'obo-portfolio', label: 'Independent OBO tokens per MCP' },
      { credential: 'internal',      label: 'All partial analyses collected' },
      { credential: 'managed-identity', label: 'Synthesis result -> Cosmos via MI' },
    ],
    observations: [
      'Single raw_token generates multiple distinct OBO tokens — each scoped to one service, eliminating lateral movement risk.',
      'Synthesis agent has zero tools: it can reason over all data but cannot call APIs, preventing post-synthesis data exfiltration.',
      'Compaction keeps the context window bounded regardless of session length — prevents prompt injection via oversized history.',
    ],
  },

  triage_agent: {
    pattern: 'handoff',
    patternLabel: 'HandoffBuilder: LLM-based Intent Routing + Azure AI Search RAG',
    securityLevel: 'INTERNAL',
    description: 'The triage agent uses LLM reasoning to route queries to the correct specialist. Azure AI Search provides RAG-retrieved research documents to augment routing decisions. The triage agent never fetches data directly — it only routes.',
    highlightOBO: false,
    steps: [
      {
        nodeType: 'browser',
        title: 'Browser / SPA',
        subtitle: 'SSE streaming POST',
        detail: 'POST /api/chat/message {message, session_id, mode:"handoff"}. Frontend opens EventSource-style reader on the response body. Handoff events { type:"handoff", from_agent, to_agent } update the AgentBadge trace display.',
        fileRef: 'frontend/src/components/ChatPanel.tsx:handleSend',
      },
      {
        nodeType: 'backend',
        title: 'FastAPI + Guardrail',
        subtitle: 'Content policy + session load',
        detail: 'check_user_message() enforces input content policy (empty check + Foundry content filter). Prior messages loaded from Cosmos for conversation history. PortfolioOrchestrator.run_handoff() starts HandoffBuilder conversation.',
        fileRef: 'backend/app/core/guardrails/policy.py + routes/chat.py',
      },
      {
        nodeType: 'foundry',
        title: 'Triage Agent (LLM)',
        subtitle: 'Routes by intent + RAG context',
        detail: 'TRIAGE_INSTRUCTIONS: 7 routing rules based on intent domain. AzureAISearchContextProvider injects top-3 research documents before routing decision. SECURITY RULES in system prompt: "NEVER attempt to access portfolio data yourself". Returns specialist name or COMPREHENSIVE_ANALYSIS_REQUESTED.',
        fileRef: 'backend/app/workflows/portfolio_workflow.py:TRIAGE_INSTRUCTIONS',
      },
      {
        nodeType: 'external',
        title: 'Azure AI Search',
        subtitle: 'RAG: portfolio-research index',
        detail: 'Semantic search (top_k=3) over portfolio-research index. Documents: investment theses, market analyses, research notes. Credentials: Managed Identity (no API key if azure_search_api_key empty). Augments triage context before routing.',
        fileRef: 'backend/app/core/workflows/base.py:_initialize:AzureAISearchContextProvider',
      },
      {
        nodeType: 'backend',
        title: 'Specialist Handoff',
        subtitle: 'SSE: handoff event -> specialist',
        detail: 'HandoffBuilder emits {type:"handoff", from_agent:"triage_agent", to_agent:"<specialist>"}. Frontend renders trace pill. Specialist agent receives full conversation history and activates its auth pattern (OBO / API key / OAuth / A2A).',
        fileRef: 'backend/app/core/workflows/base.py:_process_workflow_event',
      },
    ],
    arrows: [
      { credential: 'entra-jwt',        label: 'Bearer Entra JWT (role-based access)' },
      { credential: 'internal',         label: 'Session history from Cosmos' },
      { credential: 'managed-identity', label: 'Semantic search via MI' },
      { credential: 'internal',         label: 'Handoff event -> specialist activates' },
    ],
    observations: [
      'LLM-based routing handles paraphrases and cross-domain queries that keyword matching would miss.',
      'RAG context from AI Search means triage can route informed by proprietary research, not just prompt instructions.',
      'Prompt injection defense is layered: guardrail middleware + explicit SECURITY RULES in triage system prompt.',
    ],
  },

  // ── Multi-IDP / Okta Proxy demo variants ────────────────────────────────

  'private_data_agent__multi-idp': {
    pattern: 'multi-idp',
    patternLabel: 'Option B: Multi-IDP + Mock Okta JWT (market.read)',
    securityLevel: 'PUBLIC',
    description: 'Instead of Entra OBO, the backend requests a mock Okta JWT from the mock-OIDC server (simulating Copilot Studio). Yahoo Finance MCP validates it via MultiIDPTokenVerifier — auto-discovering JWKS from the trusted issuer. Zero code change to the MCP; only TRUSTED_ISSUERS env var is set.',
    highlightOBO: false,
    steps: [
      { nodeType: 'browser',    title: 'Browser / SPA',          subtitle: 'Optional Entra token',                 detail: 'Market data is public. demo_mode=multi-idp in request body tells the backend to use the mock Okta flow instead of OBO.',                                                                                              fileRef: 'frontend/src/components/ChatPanel.tsx' },
      { nodeType: 'backend',    title: 'FastAPI Backend',         subtitle: 'POST /token to mock-OIDC',            detail: '_fetch_mock_oidc_tokens(): POST http://localhost:8889/token with sub=user_email, audience=api://<yahoo-mcp-client-id>, scope=market.read. Two tokens fetched (yahoo + portfolio).',                               fileRef: 'backend/app/workflows/portfolio_workflow.py:_fetch_mock_oidc_tokens' },
      { nodeType: 'external',   title: 'Mock OIDC Server',        subtitle: 'Simulates Okta / Copilot Studio IDP', detail: 'RS256 JWT: iss=http://localhost:8889, aud=api://<yahoo-mcp-client-id>, scp=market.read. RSA key generated at startup; JWKS served at /keys. OIDC discovery at /.well-known/openid-configuration.',              fileRef: 'mcp-servers/mock-oidc/server.py:_mint_token' },
      { nodeType: 'mcp-public', title: 'Yahoo Finance MCP',       subtitle: 'MultiIDPTokenVerifier',               detail: 'TRUSTED_ISSUERS=http://localhost:8889. Auto-discovers JWKS, validates RS256, checks aud. check_scope("market.read") reads scp from _request_claims ContextVar set by verifier.',                               fileRef: 'mcp-servers/yahoo-finance/entra_auth.py:MultiIDPTokenVerifier' },
      { nodeType: 'data',       title: 'yfinance / Yahoo Finance', subtitle: 'Public market data',                 detail: 'Same yfinance tools as Entra mode. Token validation is the only difference — data retrieval is identical.',                                                                                                         fileRef: 'mcp-servers/yahoo-finance/server.py' },
    ],
    arrows: [
      { credential: 'none',      label: 'No token (public data)' },
      { credential: 'mock-oidc', label: 'POST /token — sub, audience, scope' },
      { credential: 'mock-oidc', label: 'RS256 JWT (iss=mock-oidc, scp=market.read)' },
      { credential: 'mock-oidc', label: 'JWKS validated + scope checked' },
    ],
    observations: [
      'TRUSTED_ISSUERS env var activates MultiIDPTokenVerifier — zero MCP code changes required.',
      'Mock OIDC simulates the Copilot Studio Okta IDP; the MCP cannot distinguish it from a real Okta token.',
      '_request_claims ContextVar bridges verifier and tool functions — no fragile header re-parsing.',
    ],
  },

  'private_data_agent__okta-proxy': {
    pattern: 'okta-proxy',
    patternLabel: 'Option C: Okta Proxy + Token Swap (client_credentials)',
    securityLevel: 'PUBLIC',
    description: 'Backend sends mock Okta JWT to the Okta proxy (localhost:8003). Proxy validates via mock-OIDC JWKS, maps user identity, then calls Entra client_credentials to obtain a real service token for Yahoo Finance MCP. No second login prompt for Copilot Studio users.',
    highlightOBO: false,
    steps: [
      { nodeType: 'browser',    title: 'Browser / SPA',          subtitle: 'Optional Entra token',               detail: 'demo_mode=okta-proxy routes Yahoo Finance calls through the Okta proxy. Backend already holds the mock JWT.',                                                                                                             fileRef: 'frontend/src/components/ChatPanel.tsx' },
      { nodeType: 'backend',    title: 'FastAPI Backend',         subtitle: 'Routes to okta-proxy URL',           detail: 'PrivateDataAgent.build_tools(): effective_url=settings.okta_proxy_url (http://localhost:8003). Bearer = mock Okta JWT. MCP client transparently connects to the proxy.',                                            fileRef: 'backend/app/agents/private_data.py:build_tools' },
      { nodeType: 'external',   title: 'Okta Proxy',              subtitle: 'Validates + token swap',             detail: 'Validates mock JWT via mock-OIDC JWKS discovery. Maps sub (demo@hackathon.local). Calls Entra /token with client_credentials (api://<MCP_CLIENT_ID>/.default). Caches service token with 60s TTL buffer.',          fileRef: 'mcp-servers/okta-proxy/server.py:proxy' },
      { nodeType: 'entra',      title: 'Entra Token Exchange',    subtitle: 'client_credentials grant',           detail: 'POST /oauth2/v2.0/token grant_type=client_credentials. Returns v1 STS token: iss=sts.windows.net/{tid}/, roles=[mcp.call]. User identity forwarded via X-MCP-User-Id header.',                                    fileRef: 'mcp-servers/okta-proxy/server.py:_get_entra_service_token' },
      { nodeType: 'mcp-public', title: 'Yahoo Finance MCP',       subtitle: 'v1 STS + mcp.call role',            detail: 'MultiIDPTokenVerifier: entra_v1_issuer (sts.windows.net) added to trusted list. Validates via Entra JWKS. check_scope accepts roles=[mcp.call] as blanket app permission.',                                        fileRef: 'mcp-servers/yahoo-finance/entra_auth.py:MultiIDPTokenVerifier' },
      { nodeType: 'data',       title: 'yfinance / Yahoo Finance', subtitle: 'Public market data',                detail: 'Same data as Entra mode. User identity from X-MCP-User-Id logged for audit trail.',                                                                                                                                 fileRef: 'mcp-servers/yahoo-finance/server.py' },
    ],
    arrows: [
      { credential: 'none',         label: 'No token (public data)' },
      { credential: 'mock-oidc',    label: 'Bearer mock-Okta JWT to proxy' },
      { credential: 'mock-oidc',    label: 'JWKS validated, user mapped' },
      { credential: 'client-creds', label: 'Entra service token (roles: mcp.call)' },
      { credential: 'client-creds', label: 'v1 STS validated + mcp.call role' },
    ],
    observations: [
      'Proxy solves Copilot Studio double-auth: users never see a second login prompt.',
      'client_credentials token carries roles=[mcp.call] — accepted by check_scope() as blanket app permission.',
      'sts.windows.net v1 issuer explicitly trusted — client_credentials always uses v1; OBO uses v2.',
    ],
  },

  'portfolio_agent__multi-idp': {
    pattern: 'multi-idp',
    patternLabel: 'Option B: Multi-IDP + Mock Okta JWT (portfolio.read)',
    securityLevel: 'CONFIDENTIAL',
    description: 'Instead of Entra OBO, the backend fetches a mock Okta JWT for portfolio.read scope. Portfolio DB MCP validates via MultiIDPTokenVerifier. User sub (demo@hackathon.local) from the mock JWT is used for row-level security — same SQL enforcement as Entra mode.',
    highlightOBO: false,
    steps: [
      { nodeType: 'browser',     title: 'Browser (MSAL)',          subtitle: 'Entra token (user identity)',   detail: 'Entra token identifies the user. OID/email used as sub when minting the mock JWT. demo_mode=multi-idp skips the OBO exchange.',                                                                                          fileRef: 'frontend/src/authConfig.ts' },
      { nodeType: 'backend',     title: 'FastAPI Backend',          subtitle: 'POST /token to mock-OIDC',     detail: '_fetch_mock_oidc_tokens(): POST http://localhost:8889/token with audience=api://<portfolio-mcp-client-id>, scope=portfolio.read, sub=user_email or demo@hackathon.local.',                                            fileRef: 'backend/app/workflows/portfolio_workflow.py:_fetch_mock_oidc_tokens' },
      { nodeType: 'external',    title: 'Mock OIDC Server',         subtitle: 'Simulates Okta IDP',           detail: 'RS256 JWT: iss=http://localhost:8889, aud=api://<portfolio-mcp-client-id>, scp=portfolio.read, sub=demo@hackathon.local.',                                                                                            fileRef: 'mcp-servers/mock-oidc/server.py:_mint_token' },
      { nodeType: 'mcp-private', title: 'Portfolio DB MCP',         subtitle: 'MultiIDPTokenVerifier + RLS',  detail: 'TRUSTED_ISSUERS=http://localhost:8889. check_scope("portfolio.read") validates scp. get_user_id_from_request() reads sub from _request_claims ContextVar for SQL RLS.',                                              fileRef: 'mcp-servers/portfolio-db/entra_auth.py:MultiIDPTokenVerifier' },
      { nodeType: 'data',        title: 'SQLite / Fabric',          subtitle: 'SQL Row-Level Security',       detail: 'WHERE user_id = demo@hackathon.local — same RLS enforcement as Entra mode; only identity source changes from oid to sub.',                                                                                             fileRef: 'mcp-servers/portfolio-db/server.py:_db_get_holdings' },
    ],
    arrows: [
      { credential: 'entra-jwt', label: 'Bearer Entra JWT (identify user)' },
      { credential: 'mock-oidc', label: 'POST /token — sub=user, audience, scp' },
      { credential: 'mock-oidc', label: 'RS256 JWT (scp=portfolio.read)' },
      { credential: 'mock-oidc', label: 'JWKS validated + scope + RLS' },
    ],
    observations: [
      'Row-level security still enforced — identity source changes from Entra oid to mock JWT sub claim.',
      'MultiIDPTokenVerifier is drop-in: only TRUSTED_ISSUERS env var changes, no MCP code modifications.',
      'In production: replace mock-OIDC URL with real Okta issuer in TRUSTED_ISSUERS.',
    ],
  },
}

// --- Agent name normalization ---

function getFlow(agent: string, demoMode?: string): FlowDef | null {
  if (!agent) return null
  const candidates = [
    agent,
    agent + '_agent',
    agent.replace(/_agent$/, '') + '_agent',
    agent.replace(/_agent$/, ''),
  ]
  for (const key of candidates) {
    if (FLOWS[key]) {
      if (demoMode && demoMode !== 'entra') {
        const variant = FLOWS[`${key}__${demoMode}`]
        if (variant) return variant
      }
      return FLOWS[key]
    }
  }
  return null
}

// --- JWT decode (base64 payload only — display purposes, no signature verification) ---

interface JWTClaims {
  aud?: string | string[]
  iss?: string
  oid?: string
  preferred_username?: string
  upn?: string
  scp?: string
  scope?: string
  exp?: number
  tid?: string
  appid?: string
  azp?: string
  name?: string
  [key: string]: unknown
}

function decodeJWT(token: string): JWTClaims | null {
  try {
    const parts = token.split('.')
    if (parts.length < 2) return null
    const b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const pad = b64.length % 4 ? '='.repeat(4 - (b64.length % 4)) : ''
    return JSON.parse(atob(b64 + pad)) as JWTClaims
  } catch {
    return null
  }
}

function fmtExp(exp: number | undefined): string {
  if (!exp) return 'n/a'
  return new Date(exp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

// --- Icon components (heroicons 2.0 outline paths) ---

function NodeIcon({ type, className }: { type: NodeType; className?: string }) {
  const cls = className ?? 'w-4 h-4'
  const paths: Record<NodeType, string> = {
    browser:      'M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-1.125-.621A3 3 0 0 1 14.25 18.257V17.25m6.75 3.75H3m15 0a3 3 0 0 0 3-3m-18 3a3 3 0 0 0 3-3m12 0V9.75m0 0H6.75M15 9.75V6.75m0 3H9',
    backend:      'M21.75 17.25v.75A3 3 0 0 1 18.75 21H5.25A3 3 0 0 1 2.25 18v-.75M3.75 5.25h16.5M3.75 9.75h16.5M3.75 14.25h16.5',
    entra:        'M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z',
    obo:          'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99',
    'mcp-private':'M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75M3.75 21.75h16.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H3.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z',
    'mcp-public': 'M13.5 10.5V6.75a4.5 4.5 0 1 1 9 0v3.75M3.75 21.75h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H3.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z',
    external:     'M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z',
    data:         'M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0a2.25 2.25 0 0 0-.75-1.686c-.75-.75-2.25-1.064-3.75-1.064H7.5c-1.5 0-3 .314-3.75 1.064A2.25 2.25 0 0 0 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375',
    foundry:      'M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z',
    a2a:          'M7.5 21 3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5',
    github:       'M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5',
    cosmos:       'M12 21a9.004 9.004 0 0 0 8.716-6.747M12 21a9.004 9.004 0 0 1-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 0 1 7.843 4.582M12 3a8.997 8.997 0 0 0-7.843 4.582m15.686 0A11.953 11.953 0 0 1 12 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0 1 21 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0 1 12 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 0 1 3 12c0-1.605.42-3.113 1.157-4.418',
  }
  return (
    <svg className={cls} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
      <path strokeLinecap="round" strokeLinejoin="round" d={paths[type] ?? paths.backend} />
    </svg>
  )
}

// --- FlowNode ---

interface FlowNodeProps {
  step: FlowStep
  index: number
  active: boolean
  onClick: () => void
}

function FlowNode({ step, index, active, onClick }: FlowNodeProps) {
  const s = NODE_STYLES[step.nodeType]
  return (
    <button
      onClick={onClick}
      className={`
        flow-node relative flex-shrink-0 w-44 rounded-xl border text-left transition-all duration-150 cursor-pointer
        ${s.border} ${active ? `${s.ring} ring-2 scale-[1.03] shadow-xl` : 'ring-1 ring-white/5 hover:ring-2 hover:scale-[1.02]'}
        bg-gray-900/90
      `}
    >
      {/* Colored header strip */}
      <div className={`${s.headerBg} rounded-t-xl px-3 py-2 flex items-center gap-2 border-b border-white/5`}>
        <span className={s.icon}>
          <NodeIcon type={step.nodeType} className="w-3.5 h-3.5" />
        </span>
        <span className={`text-[10px] font-bold uppercase tracking-wide ${s.title}`}>{step.title}</span>
        <span className="ml-auto text-[9px] text-gray-600 font-mono">{index + 1}</span>
      </div>
      {/* Body */}
      <div className="px-3 py-2 space-y-1.5">
        <p className="text-[10px] font-semibold text-gray-300 leading-tight">{step.subtitle}</p>
        <p className="text-[10px] text-gray-500 leading-relaxed line-clamp-3">{step.detail}</p>
      </div>
      {/* File ref */}
      <div className="px-3 pb-2">
        <span className="font-mono text-[9px] text-amber-500/70 block truncate leading-tight" title={step.fileRef}>
          {step.fileRef}
        </span>
      </div>
    </button>
  )
}

// --- FlowArrow ---

function FlowArrow({ arrow }: { arrow: FlowArrow }) {
  const c = CRED_STYLES[arrow.credential]
  return (
    <div className="flex-shrink-0 flex flex-col items-center justify-center w-20 gap-1.5 relative">
      {/* Credential badge */}
      <span className={`${c.bg} ${c.text} ${c.ring} ring-1 rounded-full px-1.5 py-0.5 text-[8px] font-semibold text-center leading-tight max-w-full whitespace-normal`}>
        {arrow.label}
      </span>
      {/* Arrow line */}
      <div className="flex items-center w-full">
        <div className="flex-1 h-px bg-gray-600/60" />
        <svg className="w-2.5 h-2.5 text-gray-500 flex-shrink-0 -ml-0.5" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clipRule="evenodd" />
        </svg>
      </div>
    </div>
  )
}

// --- StepDetail (expanded view when a node is clicked) ---

function StepDetail({ step }: { step: FlowStep }) {
  const s = NODE_STYLES[step.nodeType]
  return (
    <div className={`rounded-xl border ${s.border} bg-gray-900/70 p-4 mt-3 space-y-2`}>
      <div className="flex items-center gap-2">
        <span className={s.icon}>
          <NodeIcon type={step.nodeType} className="w-4 h-4" />
        </span>
        <span className={`text-sm font-semibold ${s.title}`}>{step.title}</span>
        <span className="text-xs text-gray-500 ml-1">{step.subtitle}</span>
      </div>
      <p className="text-xs text-gray-300 leading-relaxed">{step.detail}</p>
      <div className="flex items-center gap-2 pt-1">
        <svg className="w-3 h-3 text-amber-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5" />
        </svg>
        <span className="font-mono text-[10px] text-amber-500/80">{step.fileRef}</span>
      </div>
    </div>
  )
}

// --- Live JWT Claims Viewer ---

interface ClaimsViewerProps {
  flow: FlowDef
}

const CLAIM_DESCRIPTIONS: Record<string, string> = {
  aud:                'Audience — which service this token is FOR (must match backend API client ID)',
  iss:                'Issuer — the Entra endpoint that signed this token',
  oid:                'Object ID — your stable unique identity in Entra (used for RLS and token lookup)',
  preferred_username: 'UPN — your user principal name / email (used as partition key in Cosmos)',
  upn:                'User Principal Name — your email address in the tenant',
  scp:                'Delegated scopes — what actions this token grants on your behalf',
  scope:              'Delegated scopes granted to the application',
  exp:                'Expiry — token is valid until this time (typically 1 hour from issue)',
  tid:                'Tenant ID — your Entra directory',
  appid:              'App ID — the application that requested this token',
  azp:                'Authorized party — the client that received this token',
  name:               'Display name from your Entra profile',
}

function ClaimsViewer({ flow }: ClaimsViewerProps) {
  const { instance, accounts } = useMsal()
  const [claims, setClaims] = useState<JWTClaims | null>(null)
  const fetchedRef = useRef(false)

  useEffect(() => {
    if (fetchedRef.current || !accounts.length) return
    fetchedRef.current = true
    instance
      .acquireTokenSilent({ ...tokenRequest, account: accounts[0] })
      .then((r) => setClaims(decodeJWT(r.accessToken)))
      .catch(() => {})
  }, [accounts, instance])

  const keyFields = ['aud', 'iss', 'oid', 'preferred_username', 'upn', 'scp', 'scope', 'exp', 'tid', 'name']

  if (!claims) {
    return (
      <div className="rounded-xl border border-gray-700/40 bg-gray-900/50 p-4 mt-3">
        <p className="text-[11px] text-gray-500 text-center py-2">
          Sign in to see your live JWT claims decoded here.
        </p>
      </div>
    )
  }

  const visibleClaims = keyFields
    .filter((k) => claims[k] !== undefined)
    .map((k) => ({
      key: k,
      value: Array.isArray(claims[k])
        ? (claims[k] as string[]).join(' ')
        : k === 'exp'
        ? fmtExp(claims.exp)
        : String(claims[k]),
      desc: CLAIM_DESCRIPTIONS[k] ?? '',
    }))

  return (
    <div className="space-y-3 mt-3">
      {/* Live Entra token claims */}
      <div className="rounded-xl border border-sky-700/30 bg-sky-950/30 overflow-hidden">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-sky-700/20 bg-sky-900/20">
          <svg className="w-3.5 h-3.5 text-sky-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25Z" />
          </svg>
          <span className="text-[11px] font-semibold text-sky-300 uppercase tracking-wide">Your Active JWT Claims</span>
          <span className="ml-auto text-[9px] font-mono text-sky-600">aud = backend API (decoded, not verified client-side)</span>
        </div>
        <div className="divide-y divide-sky-900/30">
          {visibleClaims.map(({ key, value, desc }) => (
            <div key={key} className="grid grid-cols-[6rem_1fr_auto] gap-3 px-4 py-1.5 items-start hover:bg-sky-900/10 transition-colors">
              <span className="font-mono text-[10px] text-amber-400 pt-0.5 truncate">{key}</span>
              <span className="font-mono text-[10px] text-green-300 break-all leading-relaxed">{value}</span>
              <span className="text-[9px] text-gray-600 leading-relaxed max-w-xs text-right">{desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* OBO transformation (only for patterns that use OBO) */}
      {flow.highlightOBO && (
        <div className="rounded-xl border border-amber-700/30 bg-amber-950/20 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-amber-700/20 bg-amber-900/20">
            <svg className="w-3.5 h-3.5 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
            </svg>
            <span className="text-[11px] font-semibold text-amber-300 uppercase tracking-wide">OBO Exchange Produces</span>
            <span className="ml-auto text-[9px] font-mono text-amber-700">POST /oauth2/v2.0/token with grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer</span>
          </div>
          <div className="divide-y divide-amber-900/30">
            {[
              { key: 'aud', from: claims.aud ? String(Array.isArray(claims.aud) ? claims.aud[0] : claims.aud) : 'api://<BACKEND_CLIENT_ID>', to: flow.pattern === '1a' && flow.patternLabel.includes('portfolio') ? 'api://<PORTFOLIO_MCP_CLIENT_ID>' : 'api://<YAHOO_MCP_CLIENT_ID>', note: 'CHANGED — new audience for the target MCP only' },
              { key: 'scp', from: claims.scp ?? claims.scope ?? 'Chat.Read', to: flow.pattern === '1a' && flow.patternLabel.includes('portfolio') ? 'portfolio.read' : 'market.read', note: 'CHANGED — minimum scope for this MCP' },
              { key: 'oid', from: claims.oid ?? '(your oid)', to: claims.oid ?? '(your oid)', note: 'PRESERVED — same user identity across trust boundary' },
              { key: 'iss', from: 'login.microsoftonline.com/{tid}/v2.0', to: 'login.microsoftonline.com/{tid}/v2.0', note: 'PRESERVED — same issuer' },
            ].map(({ key, from, to, note }) => (
              <div key={key} className="grid grid-cols-[4rem_1fr_2rem_1fr_auto] gap-2 px-4 py-1.5 items-center hover:bg-amber-900/10 transition-colors">
                <span className="font-mono text-[10px] text-amber-400">{key}</span>
                <span className="font-mono text-[9px] text-gray-500 truncate" title={from}>{from}</span>
                <svg className="w-3 h-3 text-amber-600 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
                </svg>
                <span className="font-mono text-[9px] text-green-300 truncate" title={to}>{to}</span>
                <span className={`text-[8px] font-medium px-1.5 py-0.5 rounded-full whitespace-nowrap ${note.startsWith('CHANGED') ? 'bg-amber-900/60 text-amber-300' : 'bg-green-900/60 text-green-300'}`}>{note.split(' — ')[0]}</span>
              </div>
            ))}
          </div>
          <div className="px-4 py-2 bg-amber-950/30 text-[9px] text-amber-700 font-mono">
            backend/app/core/auth/obo.py:OBOAuth — then validated at mcp-servers/*/entra_auth.py:EntraTokenVerifier
          </div>
        </div>
      )}

      {/* MCP validation steps (for Pattern 1a/1b) */}
      {(flow.pattern === '1a' || flow.pattern === '1b') && (
        <div className="rounded-xl border border-emerald-700/30 bg-emerald-950/20 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-emerald-700/20 bg-emerald-900/20">
            <svg className="w-3.5 h-3.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
            </svg>
            <span className="text-[11px] font-semibold text-emerald-300 uppercase tracking-wide">MCP Server Validates</span>
            <span className="ml-auto text-[9px] font-mono text-emerald-700">mcp-servers/*/entra_auth.py:EntraTokenVerifier</span>
          </div>
          <div className="divide-y divide-emerald-900/30">
            {[
              { check: 'RS256 signature', result: 'Valid', detail: 'GET JWKS from Entra, verify against kid in token header' },
              { check: 'aud claim', result: 'api://<MCP_CLIENT_ID>', detail: 'Audience must match this exact MCP app registration' },
              { check: 'iss claim', result: 'login.microsoftonline.com/{tid}/v2.0', detail: 'Issuer must be the expected Entra tenant' },
              { check: 'exp claim', result: 'Not expired', detail: 'Token expiry validated on every request' },
              { check: 'scp claim', result: 'portfolio.read / market.read', detail: 'check_scope() called inside every tool function' },
              ...(flow.securityLevel === 'CONFIDENTIAL' ? [
                { check: 'oid claim', result: claims?.oid ?? '(user oid)', detail: 'Used as SQL parameter for row-level security: WHERE user_id = ?' },
              ] : []),
            ].map(({ check, result, detail }) => (
              <div key={check} className="grid grid-cols-[7rem_1fr_1fr] gap-3 px-4 py-1.5 items-center hover:bg-emerald-900/10 transition-colors">
                <span className="font-mono text-[9px] text-emerald-400">{check}</span>
                <span className="font-mono text-[9px] text-green-300">{result}</span>
                <span className="text-[9px] text-gray-500">{detail}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// --- Main AuthFlowPanel ---

interface AuthFlowPanelProps {
  agent: string
  open: boolean
  onClose: () => void
  demoMode?: string
}

export function AuthFlowPanel({ agent, open, onClose, demoMode }: AuthFlowPanelProps) {
  const [activeStep, setActiveStep] = useState<number | null>(null)
  const [showClaims, setShowClaims] = useState(false)
  const [showObs, setShowObs] = useState(false)

  const flow = getFlow(agent, demoMode)

  if (!open || !flow) return null

  const patStyle = PATTERN_STYLES[flow.pattern]
  const secStyle = SEC_STYLES[flow.securityLevel]

  const handleStepClick = (i: number) => setActiveStep(activeStep === i ? null : i)

  return (
    <div className="auth-flow-panel mt-3 rounded-2xl border border-white/8 bg-gray-950/95 shadow-2xl shadow-black/60 ring-1 ring-inset ring-white/5 overflow-hidden">

      {/* ── Header ── */}
      <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-white/5 bg-gray-900/60">
        <svg className="w-4 h-4 text-indigo-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
        </svg>
        <span className="text-[11px] font-bold text-gray-300 uppercase tracking-[0.1em]">Security Trace</span>
        <span className={`${patStyle.bg} ${patStyle.text} ${patStyle.ring} ring-1 rounded-full px-2 py-0.5 text-[9px] font-semibold`}>
          {flow.patternLabel}
        </span>
        <span className={`${secStyle.bg} ${secStyle.text} ${secStyle.ring} ring-1 rounded-full px-2 py-0.5 text-[9px] font-semibold flex items-center gap-1`}>
          <span className={`w-1.5 h-1.5 rounded-full ${secStyle.dot} inline-block`} />
          {flow.securityLevel}
        </span>
        {demoMode && demoMode !== 'entra' && (
          <span className={`${demoMode === 'okta-proxy' ? 'bg-rose-950 text-rose-300 ring-rose-700/50' : 'bg-orange-950 text-orange-300 ring-orange-700/50'} ring-1 rounded-full px-2 py-0.5 text-[9px] font-semibold`}>
            {demoMode === 'multi-idp' ? 'Multi-IDP demo' : 'Okta Proxy demo'}
          </span>
        )}
        <button
          onClick={onClose}
          className="ml-auto text-gray-600 hover:text-gray-300 transition-colors p-0.5 rounded hover:bg-gray-700/60"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="p-4 space-y-4">

        {/* Description */}
        <p className="text-[11px] text-gray-400 leading-relaxed border-l-2 border-indigo-500/40 pl-3">
          {flow.description}
        </p>

        {/* ── Flow pipeline ── */}
        <div>
          <p className="text-[10px] font-semibold text-gray-600 uppercase tracking-wide mb-2.5">
            End-to-End Flow — click any step for details
          </p>
          <div className="overflow-x-auto pb-2">
            <div className="flex items-center min-w-max gap-0">
              {flow.steps.map((step, i) => (
                <div key={i} className="flex items-center">
                  <FlowNode
                    step={step}
                    index={i}
                    active={activeStep === i}
                    onClick={() => handleStepClick(i)}
                  />
                  {i < flow.arrows.length && (
                    <FlowArrow arrow={flow.arrows[i]} />
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Expanded step detail */}
          {activeStep !== null && (
            <StepDetail step={flow.steps[activeStep]} />
          )}
        </div>

        {/* ── Token Claims Viewer ── */}
        <div>
          <button
            onClick={() => setShowClaims((v) => !v)}
            className="flex items-center gap-2 text-[10px] font-semibold text-gray-500 hover:text-gray-300 transition-colors uppercase tracking-wide py-1 group"
          >
            <svg
              className={`w-3 h-3 transition-transform ${showClaims ? 'rotate-90' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            JWT Claims Inspector
            {flow.highlightOBO && (
              <span className="bg-amber-950 text-amber-400 ring-1 ring-amber-700/50 rounded-full px-1.5 py-px text-[8px] font-semibold ml-1">
                OBO transformation
              </span>
            )}
            <span className="text-[9px] text-gray-700 normal-case">
              {flow.highlightOBO
                ? 'live Entra claims + OBO exchange + MCP validation'
                : 'live Entra claims (if authenticated)'}
            </span>
          </button>
          {showClaims && <ClaimsViewer flow={flow} />}
        </div>

        {/* ── Key Security Observations ── */}
        <div>
          <button
            onClick={() => setShowObs((v) => !v)}
            className="flex items-center gap-2 text-[10px] font-semibold text-gray-500 hover:text-gray-300 transition-colors uppercase tracking-wide py-1"
          >
            <svg
              className={`w-3 h-3 transition-transform ${showObs ? 'rotate-90' : ''}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
            Key Security Properties
          </button>
          {showObs && (
            <ul className="mt-2 space-y-1.5">
              {flow.observations.map((obs, i) => (
                <li key={i} className="flex items-start gap-2 text-[11px] text-gray-400 leading-relaxed">
                  <svg className="w-3 h-3 text-emerald-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                  </svg>
                  {obs}
                </li>
              ))}
            </ul>
          )}
        </div>

      </div>
    </div>
  )
}
