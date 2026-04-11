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
# ============================================================
from abc import ABC
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from agent_framework import Agent


class BaseAgent(ABC):
    """Abstract base for domain agents.

    Subclasses declare ``name``, ``description``, and ``system_message`` as
    class-level attributes, then implement ``build_tools(**kwargs)`` to supply
    any tools the agent needs.

    The default ``create(client, **kwargs)`` classmethod wires everything
    together and returns an ``Agent`` with history-persistence enabled.
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    system_message: ClassVar[str] = ""

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
