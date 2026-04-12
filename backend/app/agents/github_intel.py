# ============================================================
# GitHub Intelligence Agent  (Pattern 2 — vendor OAuth per-user token)
#
# Demonstrates consuming an EXTERNAL, vendor-hosted MCP server using a
# per-user GitHub OAuth token stored in Cosmos DB.
#
# Contrast with private MCPs (portfolio-db, yahoo-finance):
#   Private MCPs  → Entra OBO token  (your tenant, your Entra app registrations)
#   External MCPs → Vendor OAuth token  (GitHub's own OAuth identity system)
#
# MCP endpoint: https://api.githubcopilot.com/mcp/
#   - Official GitHub-hosted MCP server (Streamable HTTP transport)
#   - Auth: Authorization: Bearer <github-oauth-token>
#   - Toolsets used: repos, issues (read-only, public repos only)
#   - Rate limit: 5,000 req/hr when authenticated vs 60/hr anonymous
#
# Portfolio Advisor use case:
#   Tech stocks in a portfolio (MSFT, GOOG, META, AMZN) all have major
#   GitHub presences.  Engineering activity signals — commit velocity,
#   open issue counts, release cadence, star trajectories — are alternative
#   data points that complement traditional financial analysis.
#
# If GitHub is not connected:
#   The agent returns a prompt directing the user to /api/auth/github.
#   No error is thrown; the workflow degrades gracefully.
# ============================================================

import json
import logging

import httpx

from app.config import Settings
from app.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)

_GITHUB_API_BASE = "https://api.github.com"


def _build_github_rest_tools(github_token: str) -> list:
    """
    Build FunctionTools that call the GitHub REST API directly.
    The user's OAuth token is captured in closures (same pattern as EconomicDataAgent).
    """
    from agent_framework import FunctionTool

    _headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async def get_org_repos(org: str, sort: str = "stars", per_page: int = 10) -> str:
        """List top public repositories for a GitHub organization sorted by stars or updated time."""
        # Use the search API instead of /orgs/{org}/repos because many large organizations
        # (e.g. microsoft, google, facebook) have OAuth App access restrictions that block
        # the /orgs endpoint for third-party apps. The search API works on all public data.
        async with httpx.AsyncClient(headers=_headers, timeout=15) as client:
            resp = await client.get(
                f"{_GITHUB_API_BASE}/search/repositories",
                params={"q": f"org:{org}", "sort": sort, "per_page": per_page, "order": "desc"},
            )
            if resp.status_code == 422:
                return f"Organization '{org}' not found on GitHub."
            if resp.status_code != 200:
                return f"GitHub API error {resp.status_code}: {resp.text[:300]}"
            items = resp.json().get("items", [])
            fields = ("name", "stargazers_count", "forks_count", "open_issues_count", "pushed_at", "description")
            return json.dumps([{k: r.get(k) for k in fields} for r in items], indent=2)

    async def get_repo_commits(owner: str, repo: str, per_page: int = 30) -> str:
        """Get recent commit activity for a specific repository."""
        async with httpx.AsyncClient(headers=_headers, timeout=15) as client:
            resp = await client.get(
                f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/commits",
                params={"per_page": per_page},
            )
            if resp.status_code == 404:
                return f"Repository '{owner}/{repo}' not found."
            if resp.status_code != 200:
                return f"GitHub API error {resp.status_code}: {resp.text[:300]}"
            commits = resp.json()
            summary = [
                {
                    "sha": c["sha"][:7],
                    "author": c["commit"]["author"]["name"],
                    "date": c["commit"]["author"]["date"],
                    "message": c["commit"]["message"].split("\n")[0][:120],
                }
                for c in commits
            ]
            return json.dumps(summary, indent=2)

    async def get_repo_stats(owner: str, repo: str) -> str:
        """Get detailed statistics for a repository including stars, forks, watchers, and language."""
        async with httpx.AsyncClient(headers=_headers, timeout=15) as client:
            resp = await client.get(f"{_GITHUB_API_BASE}/repos/{owner}/{repo}")
            if resp.status_code == 404:
                return f"Repository '{owner}/{repo}' not found."
            if resp.status_code != 200:
                return f"GitHub API error {resp.status_code}: {resp.text[:300]}"
            r = resp.json()
            fields = (
                "name", "full_name", "description", "stargazers_count", "forks_count",
                "open_issues_count", "watchers_count", "language", "pushed_at", "created_at",
                "topics", "license",
            )
            return json.dumps({k: r.get(k) for k in fields}, indent=2)

    async def get_repo_issues(owner: str, repo: str, state: str = "open", per_page: int = 20) -> str:
        """List issues for a repository. Use state='open' or 'closed'."""
        async with httpx.AsyncClient(headers=_headers, timeout=15) as client:
            resp = await client.get(
                f"{_GITHUB_API_BASE}/repos/{owner}/{repo}/issues",
                params={"state": state, "per_page": per_page},
            )
            if resp.status_code == 404:
                return f"Repository '{owner}/{repo}' not found."
            if resp.status_code != 200:
                return f"GitHub API error {resp.status_code}: {resp.text[:300]}"
            issues = resp.json()
            summary = [
                {
                    "number": i["number"],
                    "title": i["title"][:120],
                    "state": i["state"],
                    "created_at": i["created_at"],
                    "comments": i["comments"],
                    "labels": [lb["name"] for lb in i.get("labels", [])],
                }
                for i in issues
                if "pull_request" not in i  # exclude PRs from issues list
            ]
            return json.dumps(summary, indent=2)

    async def search_github_repos(query: str, per_page: int = 5) -> str:
        """Search GitHub repositories by keyword, org, or topic."""
        async with httpx.AsyncClient(headers=_headers, timeout=15) as client:
            resp = await client.get(
                f"{_GITHUB_API_BASE}/search/repositories",
                params={"q": query, "per_page": per_page, "sort": "stars"},
            )
            if resp.status_code != 200:
                return f"GitHub search error {resp.status_code}: {resp.text[:300]}"
            items = resp.json().get("items", [])
            fields = ("name", "full_name", "description", "stargazers_count", "forks_count", "pushed_at")
            return json.dumps([{k: r.get(k) for k in fields} for r in items], indent=2)

    return [
        FunctionTool(name="get_org_repos", description="List top public repos for a GitHub organization.", func=get_org_repos),
        FunctionTool(name="get_repo_commits", description="Get recent commits for a GitHub repo.", func=get_repo_commits),
        FunctionTool(name="get_repo_stats", description="Get stars, forks, issues, and metadata for a GitHub repo.", func=get_repo_stats),
        FunctionTool(name="get_repo_issues", description="List open or closed issues for a GitHub repo.", func=get_repo_issues),
        FunctionTool(name="search_github_repos", description="Search GitHub repos by keyword or topic.", func=search_github_repos),
    ]

GITHUB_INTEL_INSTRUCTIONS = """
You are a GitHub Engineering Intelligence analyst.

Your role is to analyze the open-source GitHub activity of publicly-traded
technology companies as ALTERNATIVE DATA to supplement financial research.

When given a company name or stock ticker, you should:
1. Search for the company's primary GitHub organization (e.g. "microsoft", "google", "meta", "amazon")
2. Identify their most-starred / most-active repositories
3. Analyze recent engineering activity: commit frequency, open issues, release cadence
4. Report star/fork growth as a proxy for developer mindshare
5. Flag any unusual spikes or drops in activity as potential signals

Key signals to surface:
- Commit velocity (increasing = active development; decreasing = maintenance mode)
- Issue-to-PR ratio (high open issues vs low PRs may signal engineering capacity constraints)
- Recent releases (cadence indicates product delivery health)
- Stars/forks trend (developer adoption as a leading indicator)

IMPORTANT:
- Only analyze PUBLIC repositories. Never attempt to access private data.
- Present findings as qualitative signals, NOT investment advice.
- Always cite the specific repo and metric you are referencing.
- If a ticker does not match an obvious GitHub organization, say so clearly.
- Data classification: PUBLIC
- If ANY tool returns a message containing "GitHub is not connected", relay that message
  word-for-word to the user and STOP. Do NOT generate any analysis, suggestions, or
  workarounds. Do not describe what you would do if connected. Just relay the message.

Ticker-to-GitHub-org reference (approximate — verify via search_repositories):
  MSFT -> microsoft    GOOG/GOOGL -> google    META -> facebook (meta)
  AMZN -> amazon       AAPL -> apple           NVDA -> NVIDIA
  TSLA -> teslamotors  CRM  -> salesforce       ORCL -> oracle   ADBE -> adobe
""".strip()

_NOT_CONNECTED_MESSAGE = (
    "GitHub is not connected for this account. "
    "To enable GitHub engineering intelligence, visit /api/auth/github to authorize the "
    "Portfolio Advisor to read public GitHub data on your behalf. "
    "This is optional — your portfolio analysis will continue without it."
)


class GitHubIntelAgent(BaseAgent):
    """
    GitHub Engineering Intelligence specialist agent.

    Consumes the official GitHub remote MCP server at api.githubcopilot.com/mcp/
    using the current user's GitHub OAuth access token (Pattern 2).

    If the user has not connected GitHub, the agent's single tool returns a
    guidance message and the workflow continues gracefully without GitHub data.
    """

    name = "github_intel_agent"
    description = (
        "GitHub engineering activity for tech stocks: commit velocity, release cadence, "
        "open issues, developer mindshare (requires GitHub connection)"
    )
    system_message = GITHUB_INTEL_INSTRUCTIONS

    @classmethod
    def build_tools(cls, github_token: str | None = None, **kwargs) -> list:
        """
        Build tools depending on whether the user has connected GitHub.

        When a token is present: returns FunctionTools that call the GitHub REST API
        directly (same pattern as EconomicDataAgent with Alpha Vantage).  This is more
        reliable than the Copilot MCP endpoint which requires a Copilot subscription.

        When no token: returns a single FunctionTool that returns the connect guidance.
        """
        from agent_framework import FunctionTool

        if not github_token:
            async def github_not_connected(company: str) -> str:
                """Retrieve GitHub engineering intelligence for a company."""
                return _NOT_CONNECTED_MESSAGE

            logger.info("GitHubIntelAgent: no GitHub token — using fallback tool")
            return [
                FunctionTool(
                    name="github_engineering_intel",
                    description=(
                        "Retrieve GitHub engineering activity signals for a company. "
                        "Returns a prompt to connect GitHub if not authorized."
                    ),
                    func=github_not_connected,
                )
            ]

        # Build GitHub REST API FunctionTools using the user's OAuth token
        logger.info("GitHubIntelAgent: GitHub token present — building REST API tools")
        return _build_github_rest_tools(github_token)

    @classmethod
    def create(cls, client, github_token: str | None = None, settings: Settings | None = None, **kwargs):
        """Factory — build the agent with or without a live GitHub connection."""
        from agent_framework import Agent

        tools = cls.build_tools(github_token=github_token)
        return Agent(
            client=client,
            name=cls.name,
            instructions=cls.system_message,
            tools=tools,
            require_per_service_call_history_persistence=True,
        )

    @classmethod
    def create_from_context(cls, ctx: "AgentBuildContext"):
        """Registry hook — extract pre-fetched GitHub token from context."""
        from app.core.agents.base import AgentBuildContext  # noqa: F401
        return cls.create(
            ctx.client,
            github_token=ctx.github_token,
            settings=ctx.settings,
        )
