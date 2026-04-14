# ============================================================
# ESG Advisor A2A Server
#
# Protocol  : Agent-to-Agent (A2A) over HTTP/JSON-RPC
# Framework : LangGraph ReAct agent (LangChain tool-calling pattern)
# LLM       : Azure OpenAI  (falls back to OpenAI when AZURE_OPENAI_ENDPOINT is unset)
# Data      : Yahoo Finance sustainability scores (yfinance) -- real ESG data
#
# Exposes a single POST endpoint at / (A2A JSON-RPC) and an agent card at
# /.well-known/agent.json  so that A2AAgent in the backend can auto-discover
# the agent's capabilities.
#
# When wired into the portfolio workflow (as ESGAdvisorAgent) this agent is
# called by HandoffBuilder / ConcurrentBuilder exactly like any other specialist.
# The A2A protocol handles serialization and transport; the backend never needs
# to know this agent is powered by LangChain.
#
# References:
#   A2A spec  : https://github.com/google-deepmind/a2a
#   a2a-sdk   : https://github.com/a2a-sdk/python
#   LangGraph : https://python.langchain.com/docs/langgraph
# ============================================================

import json
import logging
import os
import time

import httpx
import uvicorn
import yfinance as yf
from dotenv import load_dotenv
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from langchain.agents import create_agent

from a2a.server.apps import A2AStarletteApplication
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Artifact,
    Part,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import get_message_text, new_agent_text_message

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent identity auth (Entra Agent ID mode — ESG_REQUIRE_AGENT_AUTH=true)
# ---------------------------------------------------------------------------
# When ESG_REQUIRE_AGENT_AUTH is "true" the server validates every incoming
# Bearer token as an Entra JWT issued to the backend's agent identity
# (DefaultAzureCredential / agent blueprint credential — no client secret).
# Set AGENT_IDENTITY_ID to the oid of the expected service principal to pin
# exactly which agent is trusted; leave empty to trust any valid Entra app token.
# ---------------------------------------------------------------------------
ESG_REQUIRE_AGENT_AUTH: bool = os.getenv("ESG_REQUIRE_AGENT_AUTH", "").lower() == "true"
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
ESG_CLIENT_ID: str = os.getenv("ESG_CLIENT_ID", "")   # app registration client id for this server
AGENT_IDENTITY_ID: str = os.getenv("AGENT_IDENTITY_ID", "")
_ESG_DEV_TOKEN: str = os.getenv("ESG_DEV_TOKEN", "dev-esg-token")

# Module-level JWKS cache shared across requests (TTL = 1 hour)
_esg_jwks_uri: str | None = None
_esg_jwks_cache: dict | None = None
_esg_jwks_fetched: float = 0.0
_JWKS_TTL: float = 3600.0


async def _verify_esg_bearer(token: str) -> dict | None:
    """Verify an Entra Bearer token for the ESG A2A server.

    Returns the decoded JWT claims on success, None on failure.
    App-only tokens (no ``scp`` claim) are additionally checked against
    AGENT_IDENTITY_ID when that env var is set.
    """
    global _esg_jwks_uri, _esg_jwks_cache, _esg_jwks_fetched

    if not ENTRA_TENANT_ID:
        # Dev mode: accept static token
        return {"sub": "dev", "dev_mode": True} if token == _ESG_DEV_TOKEN else None

    try:
        from jose import JWTError, jwt as jose_jwt  # noqa: PLC0415

        header = jose_jwt.get_unverified_header(token)
        kid = header.get("kid")
        unverified = jose_jwt.get_unverified_claims(token)
        iss: str = unverified.get("iss", "")

        entra_v2 = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
        entra_v1 = f"https://sts.windows.net/{ENTRA_TENANT_ID}/"
        if iss not in (entra_v2, entra_v1):
            logger.warning("ESG auth: rejected token issuer=%r", iss)
            return None

        # Refresh JWKS cache when stale or empty
        if not _esg_jwks_cache or (time.monotonic() - _esg_jwks_fetched) > _JWKS_TTL:
            async with httpx.AsyncClient(timeout=10) as client:
                if not _esg_jwks_uri:
                    oidc_resp = await client.get(
                        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
                        "/.well-known/openid-configuration"
                    )
                    oidc_resp.raise_for_status()
                    _esg_jwks_uri = oidc_resp.json()["jwks_uri"]
                jwks_resp = await client.get(_esg_jwks_uri)
                jwks_resp.raise_for_status()
                _esg_jwks_cache = jwks_resp.json()
                _esg_jwks_fetched = time.monotonic()

        rsa_key: dict = {}
        for key in (_esg_jwks_cache or {}).get("keys", []):
            if key.get("kid") == kid:
                rsa_key = {k: key[k] for k in ("kty", "kid", "use", "n", "e") if k in key}
                break

        if not rsa_key:
            _esg_jwks_cache = None   # force refresh on next request
            logger.warning("ESG auth: JWKS kid=%r not found; cache cleared", kid)
            return None

        audience = f"api://{ESG_CLIENT_ID}" if ESG_CLIENT_ID else None
        decode_kwargs: dict = {"algorithms": ["RS256"], "issuer": iss}
        if audience:
            decode_kwargs["audience"] = audience

        claims: dict = jose_jwt.decode(token, rsa_key, **decode_kwargs)

        # For app-only tokens (no scp), optionally enforce agent identity oid
        if AGENT_IDENTITY_ID and not claims.get("scp"):
            oid = claims.get("oid", "")
            if oid != AGENT_IDENTITY_ID:
                logger.warning(
                    "ESG auth: rejected app-only token oid=%r (expected %r)",
                    oid, AGENT_IDENTITY_ID,
                )
                return None

        return claims

    except Exception as exc:
        logger.warning("ESG bearer verification failed: %s", exc)
        return None


class _AgentAuthMiddleware:
    """Pure-ASGI middleware that enforces Entra Bearer auth on the ESG A2A server."""

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # Allow agent card discovery endpoint through without auth
        path: str = scope.get("path", "")
        if path.startswith("/.well-known"):
            await self._app(scope, receive, send)
            return

        headers: dict[bytes, bytes] = dict(scope.get("headers", []))
        raw_auth: str = headers.get(b"authorization", b"").decode()

        if not raw_auth.startswith("Bearer "):
            from starlette.responses import Response  # noqa: PLC0415
            await Response(
                "Unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return

        claims = await _verify_esg_bearer(raw_auth[7:])
        if claims is None:
            from starlette.responses import Response  # noqa: PLC0415
            await Response("Forbidden", status_code=403)(scope, receive, send)
            return

        await self._app(scope, receive, send)

# ---------------------------------------------------------------------------
# ESG Tools backed by Yahoo Finance governance risk data
#
# NOTE: Yahoo Finance removed the esgScores / sustainability endpoint in 2025.
# The tools below use the 'info' endpoint which provides Institutional
# Shareholder Services (ISS) governance risk scores (1-10, lower = better):
#   auditRisk, boardRisk, compensationRisk, shareHolderRightsRisk, overallRisk
# ---------------------------------------------------------------------------

def _fetch_governance(ticker: str) -> dict:
    """Fetch governance risk data from yfinance info endpoint."""
    t = yf.Ticker(ticker.upper().strip())
    info = t.info
    return {
        "ticker": ticker.upper(),
        "shortName": info.get("shortName", ticker.upper()),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "fullTimeEmployees": info.get("fullTimeEmployees"),
        "auditRisk": info.get("auditRisk"),          # 1-10
        "boardRisk": info.get("boardRisk"),           # 1-10
        "compensationRisk": info.get("compensationRisk"),  # 1-10
        "shareHolderRightsRisk": info.get("shareHolderRightsRisk"),  # 1-10
        "overallRisk": info.get("overallRisk"),       # 1-10 composite
        "source": "Yahoo Finance / ISS Governance (1=lowest risk, 10=highest risk)",
    }


@tool
def get_esg_scores(ticker: str) -> str:
    """Get governance risk scores for a company by stock ticker symbol.

    Returns ISS governance risk scores (audit, board, compensation, shareholder rights)
    from Yahoo Finance. Scores are 1-10 where lower = better governance.
    Note: Yahoo Finance removed granular ESG/Sustainalytics data in 2025;
    these governance scores from ISS are the available proxy.
    """
    try:
        data = _fetch_governance(ticker)
        if all(data[k] is None for k in ("auditRisk", "boardRisk", "compensationRisk", "overallRisk")):
            return f"No governance risk data available for {ticker.upper()} from Yahoo Finance."
        return json.dumps(data, indent=2, default=str)
    except Exception as exc:
        logger.warning("get_esg_scores(%s) error: %s", ticker, exc)
        return f"Could not retrieve governance data for {ticker}: {exc}"


@tool
def get_esg_peer_comparison(tickers: str) -> str:
    """Compare governance risk scores across multiple tickers (comma-separated, e.g. 'MSFT,AAPL,GOOGL').

    Returns a side-by-side comparison of ISS governance risk scores (1-10, lower = better)
    to identify which portfolio holdings have the strongest/weakest governance profiles.
    """
    symbols = [s.strip().upper() for s in tickers.split(",") if s.strip()]
    if not symbols:
        return "Please provide at least one ticker symbol."
    results = []
    for sym in symbols[:10]:
        try:
            results.append(_fetch_governance(sym))
        except Exception as exc:
            logger.warning("get_esg_peer_comparison(%s) error: %s", sym, exc)
            results.append({"ticker": sym, "status": "error", "detail": str(exc)})
    return json.dumps(results, indent=2, default=str)


@tool
def get_controversy_analysis(ticker: str) -> str:
    """Get governance risk breakdown and flags for a company by ticker.

    Returns individual ISS governance risk dimensions (audit committee, board structure,
    executive compensation, shareholder rights) plus the composite overall risk score.
    Scores are 1-10, lower is better governance.
    """
    try:
        data = _fetch_governance(ticker)
        risk_fields = {k: data[k] for k in ("auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk")}
        # Simple flag if any dimension is high risk (>=7)
        flags = [k for k, v in risk_fields.items() if v is not None and v >= 7]
        data["highRiskFlags"] = flags if flags else []
        data["interpretation"] = (
            "High risk areas (score >= 7): " + ", ".join(flags)
            if flags else "No high-risk governance dimensions detected."
        )
        return json.dumps(data, indent=2, default=str)
    except Exception as exc:
        logger.warning("get_controversy_analysis(%s) error: %s", ticker, exc)
        return f"Could not retrieve governance data for {ticker}: {exc}"


@tool
def get_sector_esg_benchmark(tickers: str) -> str:
    """Benchmark governance risk scores for a list of tickers within their sector context.

    Returns ISS overall governance risk, sector, and industry for each ticker
    and ranks them relative to each other (lower overallRisk = better governance).
    Accepts comma-separated tickers (e.g. 'MSFT,AAPL,NVDA').
    """
    symbols = [s.strip().upper() for s in tickers.split(",") if s.strip()]
    if not symbols:
        return "Please provide at least one ticker symbol."
    results = []
    for sym in symbols[:8]:
        try:
            data = _fetch_governance(sym)
            results.append({
                "ticker": sym,
                "shortName": data.get("shortName"),
                "sector": data.get("sector"),
                "industry": data.get("industry"),
                "overallRisk": data.get("overallRisk"),
                "auditRisk": data.get("auditRisk"),
                "boardRisk": data.get("boardRisk"),
                "compensationRisk": data.get("compensationRisk"),
                "shareHolderRightsRisk": data.get("shareHolderRightsRisk"),
            })
        except Exception as exc:
            results.append({"ticker": sym, "error": str(exc)})

    # Rank by overallRisk ascending (lower = better)
    ranked = sorted(
        [r for r in results if r.get("overallRisk") is not None],
        key=lambda x: x["overallRisk"],
    )
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
        r["relativeGovernance"] = (
            "Best" if i == 0 else
            "Worst" if i == len(ranked) - 1 else
            "Mid"
        )

    return json.dumps(results, indent=2, default=str)


ESG_TOOLS = [
    get_esg_scores,
    get_esg_peer_comparison,
    get_controversy_analysis,
    get_sector_esg_benchmark,
]

# ---------------------------------------------------------------------------
# LLM factory — Azure OpenAI preferred, falls back to OpenAI
# ---------------------------------------------------------------------------

def _build_llm():
    """Build the LangChain LLM from environment variables.

    Priority:
      1. Azure OpenAI  when AZURE_OPENAI_ENDPOINT is set
      2. OpenAI        when OPENAI_API_KEY is set
    """
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY") or None,
            temperature=0,
        )
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0,
    )


ESG_SYSTEM_PROMPT = """
You are an ESG (Environmental, Social, and Governance) investment analyst embedded in a
Portfolio Advisory Platform for institutional investors.

Your role is to provide objective, data-driven governance risk analysis using Yahoo Finance data
sourced from Institutional Shareholder Services (ISS).

IMPORTANT DATA NOTE: Yahoo Finance removed granular Sustainalytics ESG scores (E/S/G breakdown,
totalEsg, controversy levels) from their public API in 2025. The available data is ISS Governance
Risk Scores, which cover the Governance (G) dimension specifically.

Available data from Yahoo Finance / ISS:
- auditRisk: Audit committee independence and oversight risk (1-10)
- boardRisk: Board structure, independence, and diversity risk (1-10)
- compensationRisk: Executive compensation alignment with shareholders (1-10)
- shareHolderRightsRisk: Shareholder rights and anti-takeover provisions (1-10)
- overallRisk: Composite governance risk score (1-10)

Score interpretation (lower is better):
  1-3  Low governance risk
  4-6  Medium governance risk
  7-10 High governance risk

Core responsibilities:
- Retrieve and interpret ISS governance risk scores for individual portfolio holdings
- Compare governance profiles across holdings to identify concentration in high-risk companies
- Benchmark scores relative to peers within the same query
- Flag high-risk governance dimensions (score >= 7) that may affect long-term value
- Be transparent that E (Environmental) and S (Social) Sustainalytics scores are
  no longer available via this data source

Data classification: PUBLIC (Yahoo Finance / ISS governance disclosures)
Always note the data source and that these reflect ISS periodic assessments.
Do NOT fabricate scores; if data is unavailable, say so clearly.
""".strip()


# ---------------------------------------------------------------------------
# LangGraph ReAct agent
# ---------------------------------------------------------------------------

def _build_react_agent():
    llm = _build_llm()
    return create_agent(llm, ESG_TOOLS, system_prompt=ESG_SYSTEM_PROMPT)


# Eagerly build so startup errors surface immediately rather than on first request
try:
    _react_agent = _build_react_agent()
    logger.info("ESG ReAct agent initialized successfully")
except Exception as _err:
    logger.error("Failed to build ESG ReAct agent: %s", _err)
    raise


# ---------------------------------------------------------------------------
# A2A AgentExecutor
# ---------------------------------------------------------------------------

class ESGAdvisorExecutor(AgentExecutor):
    """Bridges the A2A server protocol to the LangGraph ReAct ESG agent."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = get_message_text(context.message)
        if not user_text or not user_text.strip():
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=new_agent_text_message("No message text provided."),
                    ),
                    final=True,
                )
            )
            return

        # Signal that we are working (allows the caller to show a progress indicator)
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message("Retrieving ESG data..."),
                ),
                final=False,
            )
        )

        try:
            result = await _react_agent.ainvoke(
                {"messages": [HumanMessage(content=user_text)]}
            )
            # LangGraph returns messages list; last message is the final AI response
            final_msg = result["messages"][-1]
            final_text = (
                final_msg.content
                if isinstance(final_msg.content, str)
                else str(final_msg.content)
            )
        except Exception as exc:
            logger.exception("ESG agent execution error: %s", exc)
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    context_id=context.context_id,
                    status=TaskStatus(
                        state=TaskState.failed,
                        message=new_agent_text_message(
                            f"ESG analysis could not be completed: {exc}"
                        ),
                    ),
                    final=True,
                )
            )
            return

        # Emit the answer as an artifact so agent_framework_a2a picks it up
        # via task.artifacts (A2AAgent._parse_messages_from_task reads artifacts first)
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=Artifact(
                    artifact_id="esg-result",
                    name="ESG Analysis",
                    parts=[Part(root=TextPart(kind="text", text=final_text))],
                ),
                append=False,
                last_chunk=True,
            )
        )

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(
                    state=TaskState.completed,
                ),
                final=True,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()


# ---------------------------------------------------------------------------
# A2A application wiring
# ---------------------------------------------------------------------------

def build_app():
    agent_card = AgentCard(
        name="ESG Advisor",
        description=(
            "ESG (Environmental, Social, Governance) ratings and sustainability analysis "
            "for individual stocks and portfolios. Provides Sustainalytics-sourced risk scores, "
            "controversy levels, peer benchmarks, and sector ESG comparisons via Yahoo Finance."
        ),
        url=f"http://localhost:{os.getenv('PORT', '8010')}",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id="esg_scores",
                name="ESG Risk Scores",
                description="Retrieve ESG risk scores (Environmental, Social, Governance) for a stock ticker",
                tags=["esg", "sustainability", "risk", "investing"],
                examples=["What is the ESG score for Microsoft?", "Get ESG ratings for AAPL"],
            ),
            AgentSkill(
                id="esg_peer_comparison",
                name="ESG Peer Comparison",
                description="Compare ESG profiles across multiple tickers in the same portfolio",
                tags=["esg", "comparison", "portfolio", "peer"],
                examples=["Compare ESG scores for MSFT, AAPL, GOOGL", "Which of my tech holdings has the best ESG rating?"],
            ),
            AgentSkill(
                id="controversy_analysis",
                name="Controversy Analysis",
                description="Analyse controversy levels and governance flags for a company",
                tags=["controversy", "governance", "esg", "risk"],
                examples=["Are there any ESG controversies for Tesla?", "Check governance flags for Meta"],
            ),
            AgentSkill(
                id="sector_esg_benchmark",
                name="Sector ESG Benchmark",
                description="Benchmark portfolio holdings against sector ESG peers (LAG/AVG/LEAD/OUT_PERF)",
                tags=["benchmark", "sector", "esg", "peer"],
                examples=["How does NVDA rank vs its sector on ESG?", "Benchmark ESG for my semiconductor holdings"],
            ),
        ],
        default_input_modes=["text"],
        default_output_modes=["text"],
    )

    handler = DefaultRequestHandler(
        agent_executor=ESGAdvisorExecutor(),
        task_store=InMemoryTaskStore(),
    )
    a2a_app = A2AStarletteApplication(agent_card=agent_card, http_handler=handler).build()
    if ESG_REQUIRE_AGENT_AUTH:
        logger.info("ESG A2A server: agent identity auth ENABLED (AGENT_IDENTITY_ID=%r)", AGENT_IDENTITY_ID or "<any>")
        return _AgentAuthMiddleware(a2a_app)
    return a2a_app


app = build_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8010"))
    logger.info("Starting ESG Advisor A2A server on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)
