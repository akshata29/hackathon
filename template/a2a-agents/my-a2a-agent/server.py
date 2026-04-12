# ============================================================
# My A2A Agent — TEMPLATE STUB
#
# Protocol  : Agent-to-Agent (A2A) over HTTP/JSON-RPC
# Framework : LangGraph ReAct agent (LangChain tool-calling pattern)
# LLM       : Azure OpenAI  (falls back to OpenAI when AZURE_OPENAI_ENDPOINT is unset)
#
# This server exposes:
#   POST /                        A2A JSON-RPC endpoint (called by A2AAgent)
#   GET  /.well-known/agent.json  Agent card (capability advertisement)
#
# Integration with the backend:
#   1. Add a BaseAgent subclass in backend/app/agents/my_agent.py that wraps
#      A2AAgent(url=settings.my_agent_url, ...)
#   2. Register it in backend/app/agents/__init__.py
#   3. Set MY_A2A_AGENT_URL in backend/.env
#   The backend's build_specialist_agents() will auto-discover the agent via
#   the registry.
#
# Coding prompts: See template/docs/coding-prompts/README.md > Step 2b
# Reference impl: a2a-agents/esg-advisor/server.py
# ============================================================

import json
import logging
import os
import sys

import uvicorn
from dotenv import load_dotenv
from langchain.tools import tool
from langchain_core.messages import HumanMessage

from a2a.server.apps import A2AStarletteApplication
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Part,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM setup — Azure OpenAI preferred, OpenAI as fallback
# ---------------------------------------------------------------------------

def _build_llm():
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        from langchain_openai import AzureChatOpenAI
        return AzureChatOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY") or None,  # None -> managed identity
        )
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )


# ---------------------------------------------------------------------------
# Tools  (add your domain-specific tools here)
# ---------------------------------------------------------------------------

@tool
def my_tool_one(query: str) -> str:
    """TODO: Replace with a real tool.

    Describe what this tool does so the ReAct agent knows when to call it.

    Args:
        query: The user query or input to process.

    Returns:
        A string result to include in the agent's response.
    """
    # TODO: implement real logic (API call, DB query, computation, ...)
    return f"[stub] my_tool_one called with: {query}"


@tool
def my_tool_two(param: str) -> str:
    """TODO: Replace with a second domain tool.

    Args:
        param: Some parameter.

    Returns:
        A string result.
    """
    # TODO: implement real logic
    return f"[stub] my_tool_two called with: {param}"


TOOLS = [my_tool_one, my_tool_two]

# ---------------------------------------------------------------------------
# System prompt for the ReAct agent
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a helpful AI agent specialised in <YOUR DOMAIN>.

You have access to the following tools:
- my_tool_one: <describe when to use tool one>
- my_tool_two: <describe when to use tool two>

Always use the tools to retrieve real data before composing your answer.
Be concise and factual.  If a tool returns an error, explain the limitation.
""".strip()

# ---------------------------------------------------------------------------
# LangGraph ReAct agent (lazy-initialised)
# ---------------------------------------------------------------------------

_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        from langgraph.prebuilt import create_react_agent
        llm = _build_llm()
        _agent = create_react_agent(llm, TOOLS, prompt=SYSTEM_PROMPT)
    return _agent


# ---------------------------------------------------------------------------
# A2A AgentExecutor
# ---------------------------------------------------------------------------

class MyAgentExecutor(AgentExecutor):
    """Bridges the A2A request lifecycle to the LangGraph ReAct agent."""

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # Extract the last user message
        user_text = ""
        for p in reversed(context.message.parts or []):
            if isinstance(p.root, TextPart):
                user_text = p.root.text
                break

        logger.info("MyAgent received: %.120s", user_text)

        # Signal that work has started
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=context.task_id,
                contextId=context.context_id,
                status=TaskStatus(state=TaskState.working),
                final=False,
            )
        )

        try:
            agent = _get_agent()
            result = await agent.ainvoke(
                {"messages": [HumanMessage(content=user_text)]}
            )
            answer = result["messages"][-1].content
        except Exception as exc:
            logger.error("Agent error: %s", exc, exc_info=True)
            answer = f"An error occurred while processing your request: {exc}"

        # Return the final answer
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=context.task_id,
                contextId=context.context_id,
                status=TaskStatus(
                    state=TaskState.completed,
                    message={"parts": [{"kind": "text", "text": answer}]},
                ),
                final=True,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancellation not supported")


# ---------------------------------------------------------------------------
# Agent card (capability advertisement)
# ---------------------------------------------------------------------------

AGENT_CARD = AgentCard(
    name="My A2A Agent",                          # TODO: rename
    description="TODO: describe what this agent does",
    url=f"http://localhost:{os.getenv('PORT', '8010')}/",
    version="0.1.0",
    capabilities=AgentCapabilities(streaming=False),
    defaultInputModes=["text"],
    defaultOutputModes=["text"],
    skills=[
        AgentSkill(
            id="my_skill",
            name="My Domain Skill",               # TODO: rename
            description="TODO: describe the skill",
            inputModes=["text"],
            outputModes=["text"],
        ),
    ],
)

# ---------------------------------------------------------------------------
# Application entry-point
# ---------------------------------------------------------------------------

def build_app():
    request_handler = DefaultRequestHandler(
        agent_executor=MyAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )
    app = A2AStarletteApplication(
        agent_card=AGENT_CARD,
        http_handler=request_handler,
    )
    return app.build()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8010"))
    logger.info("Starting My A2A Agent on port %d", port)
    uvicorn.run(build_app(), host="0.0.0.0", port=port)
