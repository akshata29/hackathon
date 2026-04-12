# ============================================================
# BaseAgent — abstract base class for all agents in the system.
#
# Domain agents (in app/agents/) extend this to get consistent
# creation, tool wiring, and history-persistence settings.
#
# Usage pattern:
#
#   class MyAgent(BaseAgent):
#       name = "my_agent"
#       description = "What this agent does"
#       system_message = MY_INSTRUCTIONS
#
#       @classmethod
#       def build_tools(cls, my_mcp_url: str, **kwargs) -> list:
#           from agent_framework import MCPStreamableHTTPTool
#           return [MCPStreamableHTTPTool(name="MyTool", url=f"{my_mcp_url}/mcp", ...)]
#
#   # Instantiate:
#   agent = MyAgent.create(client, my_mcp_url="http://...")
#
# Override create() entirely when you need a non-standard client (e.g.
# MarketIntelAgent uses RawFoundryAgentChatClient instead of FoundryChatClient).
#
# Agent Registry — dynamic discovery:
#   Every subclass with a non-empty ``name`` is automatically registered in
#   BaseAgent._registry at class-definition time via __init_subclass__.
#   Orchestrators call BaseAgent.registered_agents() to enumerate all known
#   agents and build the specialist list without importing them explicitly.
#   Each agent also implements create_from_context(ctx) so the registry loop
#   can instantiate any agent from a single AgentBuildContext bag.
#
#   To add a new agent:
#     1. Create app/agents/my_agent.py  (extend BaseAgent, set name/description)
#     2. Implement create_from_context(ctx)
#     3. Add an import in app/agents/__init__.py
#   The orchestrator discovers it automatically — no other changes needed.
# ============================================================
from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from agent_framework import Agent


@dataclass
class AgentBuildContext:
    """Context bag passed to ``create_from_context()``.

    Holds every resource an agent might need during construction so that the
    registry-driven build loop only needs to call one method per agent class.

    Attributes:
        client:            Shared FoundryChatClient for inference.
        credential:        Shared AsyncTokenCredential (DefaultAzureCredential).
        settings:          Application Settings instance.
        user_token:        Stable user identifier (email / oid) for session
                           scoping and dev-mode row-level security headers.
        raw_token:         Raw Entra Bearer JWT. Present in production when OBO
                           exchange should be used. None in dev mode.
        context_providers: Optional list of ContextProviders injected into the
                           triage agent (e.g. AzureAISearchContextProvider).
        vendor_tokens:     Dict of per-user vendor OAuth tokens keyed by
                           provider name (e.g. {"github": "<token>"}).
                           Used for Pattern 2 (vendor OAuth per-user) agents.
    """

    client: Any
    credential: Any
    settings: Any
    user_token: str | None = None
    raw_token: str | None = None
    context_providers: list | None = field(default=None)
    vendor_tokens: dict = field(default_factory=dict)


class BaseAgent(ABC):
    """Abstract base for domain agents.

    Subclasses declare ``name``, ``description``, and ``system_message`` as
    class-level attributes, then implement ``build_tools(**kwargs)`` to supply
    any tools the agent needs.

    The default ``create(client, **kwargs)`` classmethod wires everything
    together and returns an ``Agent`` with history-persistence enabled.

    Agent Registry
    --------------
    Every concrete subclass with a non-empty ``name`` is automatically
    registered in ``_registry`` at class-definition time.  Call
    ``BaseAgent.registered_agents()`` to get the current snapshot.

    Dynamic construction
    --------------------
    Each agent must also implement ``create_from_context(ctx)`` so that the
    orchestrator's build loop can instantiate all registered agents uniformly
    from a single ``AgentBuildContext``.  Return ``None`` to skip an agent
    when its required config (URL, token, etc.) is absent — the build loop
    silently filters out None values.
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    system_message: ClassVar[str] = ""

    # Populated automatically via __init_subclass__ — do not mutate directly.
    _registry: ClassVar[dict[str, "type[BaseAgent]"]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            BaseAgent._registry[cls.name] = cls

    @classmethod
    def registered_agents(cls) -> dict[str, "type[BaseAgent]"]:
        """Return a snapshot of the registry: {agent_name: agent_class}."""
        return dict(BaseAgent._registry)

    @classmethod
    def build_tools(cls, **kwargs) -> list:
        """Return the list of tools for this agent.

        Override in subclasses.  Keyword arguments are forwarded from
        ``create()`` (e.g. mcp_url, api_key, user_token).
        """
        return []

    @classmethod
    def create(cls, client, **kwargs) -> "Agent":
        """Instantiate the agent with a shared FoundryChatClient.

        Args:
            client: FoundryChatClient (or compatible) used for inference.
            **kwargs: Forwarded verbatim to ``build_tools()``.

        Returns:
            A configured ``Agent`` with ``require_per_service_call_history_persistence=True``.
        """
        from agent_framework import Agent

        return Agent(
            client=client,
            name=cls.name,
            instructions=cls.system_message,
            tools=cls.build_tools(**kwargs),
            require_per_service_call_history_persistence=True,
        )

    @classmethod
    def create_from_context(cls, ctx: AgentBuildContext) -> Any:
        """Instantiate this agent from a shared ``AgentBuildContext``.

        Override in each concrete subclass to extract the specific kwargs it
        needs from *ctx*.  This is the hook used by the registry-driven build
        loop in the orchestrator.

        Return ``None`` to opt out (e.g. when a required URL / token is absent
        in the current environment).  The build loop silently skips ``None``.

        TODO: implement this in your agent subclass, e.g.:
            @classmethod
            def create_from_context(cls, ctx):
                return cls.create(
                    ctx.client,
                    mcp_url=ctx.settings.my_mcp_url,
                    raw_token=ctx.raw_token,
                    settings=ctx.settings,
                )
        """
        raise NotImplementedError(
            f"{cls.__name__} must implement create_from_context(ctx)"
        )
