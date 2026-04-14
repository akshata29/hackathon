# ============================================================
# BaseOrchestrator — abstract base for multi-agent workflows.
#
# Provides ALL infrastructure:
#   - Credential + FoundryChatClient lifecycle (__aenter__ / __aexit__)
#   - Optional Azure AI Search context provider
#   - Token-budget compaction (CharacterEstimatorTokenizer)
#   - HandoffBuilder wiring (triage routes to specialists)
#   - ConcurrentBuilder wiring (all specialists run in parallel)
#   - SSE / WebSocket event translation (_process_workflow_event)
#   - run_handoff() streaming pipeline with triage buffering
#   - run_comprehensive() streaming pipeline
#
# Domain subclasses only need to:
#   1. Set three class vars: triage_instructions, workflow_name,
#      comprehensive_trigger (empty string = disabled)
#   2. Implement build_specialist_agents(user_token) — return a list
#      of specialist Agent instances (HandoffBuilder + ConcurrentBuilder).
#   3. Optionally override build_synthesis_agent() for a custom synthesis
#      prompt in the concurrent (all-agents) flow.
#
# References:
#   HandoffBuilder: https://github.com/microsoft/agent-framework/blob/main/python/samples/03-workflows/orchestrations/handoff_simple.py
#   ConcurrentBuilder: https://github.com/microsoft/agent-framework/tree/main/python/samples/03-workflows/orchestrations
#   Compaction: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/compaction
# ============================================================

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, ClassVar

from app.config import Settings

logger = logging.getLogger(__name__)

# Maximum wall-clock seconds for a single handoff or comprehensive workflow run.
# Prevents the UI from spinning forever when the LLM or an MCP tool hangs.
_WORKFLOW_TIMEOUT_SECS = 120


class BaseOrchestrator(ABC):
    """Abstract base orchestrator for HandoffBuilder + ConcurrentBuilder workflows.

    Override these class-level attributes in your subclass:

        triage_instructions (str)
            System prompt for the routing / triage agent.

        workflow_name (str)
            Name passed to HandoffBuilder — appears in traces.

        comprehensive_trigger (str)
            If this string appears in the triage agent's accumulated response
            text and no handoff occurred, ``run_handoff()`` automatically
            escalates to ``run_comprehensive()``.  Set to ``""`` to disable.

    Implement this abstract method:

        build_specialist_agents(user_token) -> list[Agent]
            Return the ordered list of specialist agents.  These are added
            after the triage agent in HandoffBuilder participants, and used
            directly in ConcurrentBuilder participants.

    Optional overrides:

        build_synthesis_agent() -> Agent
            The synthesis agent used by ConcurrentBuilder's aggregator.
            Default provides a generic "senior advisor" prompt.

        build_concurrent_agents(user_token) -> list[Agent]
            Defaults to build_specialist_agents(user_token).  Override when
            the concurrent set differs from the handoff set.
    """

    triage_agent_name: ClassVar[str] = "triage_agent"
    triage_instructions: ClassVar[str] = ""
    workflow_name: ClassVar[str] = "handoff_workflow"
    comprehensive_trigger: ClassVar[str] = ""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._credential = None
        self._client = None
        self._search_provider = None

    async def __aenter__(self):
        await self._initialize()
        return self

    async def __aexit__(self, *args):
        await self._cleanup()

    async def _initialize(self) -> None:
        """Set up credential, FoundryChatClient, optional Azure Monitor, and AI Search."""
        from agent_framework.foundry import FoundryChatClient
        from azure.identity.aio import DefaultAzureCredential

        self._credential = DefaultAzureCredential(
            managed_identity_client_id=self._settings.azure_client_id or None
        )
        self._client = FoundryChatClient(
            project_endpoint=self._settings.foundry_project_endpoint,
            model=self._settings.foundry_model,
            credential=self._credential,
        )

        # Configure Azure Monitor via the Foundry client (retrieves connection string
        # from the project, so no explicit connection string is required here).
        # Reference: https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/observability/foundry_tracing.py
        if self._settings.applicationinsights_connection_string:
            try:
                await self._client.configure_azure_monitor(
                    enable_sensitive_data=self._settings.enable_sensitive_data
                )
                logger.info("Azure Monitor configured via FoundryChatClient")
            except Exception as exc:
                logger.warning("Could not configure Azure Monitor via client: %s", exc)

        # AI Search context provider — injected into the triage agent so it has
        # access to RAG-retrieved documents during routing decisions.
        # Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/context_providers/azure_ai_search
        if (
            self._settings.azure_search_endpoint
            and self._settings.azure_search_index_name
        ):
            from agent_framework.azure import AzureAISearchContextProvider

            self._search_provider = AzureAISearchContextProvider(
                endpoint=self._settings.azure_search_endpoint,
                index_name=self._settings.azure_search_index_name,
                credential=(
                    self._credential
                    if not self._settings.azure_search_api_key
                    else None
                ),
                api_key=self._settings.azure_search_api_key or None,
                mode="semantic",
                top_k=3,
            )

    async def _cleanup(self) -> None:
        if self._credential:
            await self._credential.close()

    # ------------------------------------------------------------------
    # Compaction
    # ------------------------------------------------------------------

    def _get_compaction_provider(self):
        """Build the compaction provider (TokenBudgetComposedStrategy).

        Keeps the most recent tokens within budget and summarises older turns.
        Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/compaction
        """
        try:
            from agent_framework import (
                CharacterEstimatorTokenizer,
                CompactionProvider,
                SlidingWindowStrategy,
                TokenBudgetComposedStrategy,
            )

            return CompactionProvider(
                before_strategy=TokenBudgetComposedStrategy(
                    token_budget=100_000,
                    tokenizer=CharacterEstimatorTokenizer(),
                    strategies=[SlidingWindowStrategy(keep_last_groups=20)],
                )
            )
        except ImportError:
            logger.warning("Compaction not available — using full conversation history")
            return None

    # ------------------------------------------------------------------
    # Agent builders (override in subclasses as needed)
    # ------------------------------------------------------------------

    def build_triage_agent(self, context_providers=None):
        """Build the triage agent with instructions filled from the agent registry.

        If ``triage_instructions`` contains the ``{AGENT_CAPABILITIES}`` placeholder,
        it is replaced at runtime with a formatted block generated from
        ``BaseAgent.registered_agents()`` — each entry includes the agent name,
        description, and up to three example queries.  This keeps routing rules
        automatically in sync with the actual registered agents.
        """
        from agent_framework import Agent

        instructions = self.triage_instructions
        if "{AGENT_CAPABILITIES}" in instructions:
            import app.agents  # ensure all agent modules are loaded (populates registry)
            from app.core.agents.base import BaseAgent

            lines = []
            for cls in BaseAgent.registered_agents().values():
                if not cls.name or not cls.description:
                    continue
                line = f"  {cls.name}: {cls.description}"
                if cls.example_queries:
                    examples = "; ".join(cls.example_queries[:3])
                    line += f"\n    e.g. {examples}"
                lines.append(line)
            instructions = instructions.replace("{AGENT_CAPABILITIES}", "\n".join(lines))
            logger.debug("Triage instructions generated for %d agents", len(lines))

        return Agent(
            client=self._client,
            name=self.triage_agent_name,
            instructions=instructions,
            context_providers=context_providers or None,
            require_per_service_call_history_persistence=True,
        )

    @abstractmethod
    def build_specialist_agents(self, user_token: str | None = None, raw_token: str | None = None) -> list:
        """Return the ordered list of specialist agents.

        These are appended after the triage agent in HandoffBuilder participants,
        and used directly as ConcurrentBuilder participants.

        Args:
            user_token: Stable user identifier (email / oid) for session scoping
                        and dev-mode RLS headers.
            raw_token:  The user's raw Entra Bearer string.  Present in production
                        when OBO exchange should be used instead of shared secrets.
        """
        ...

    def build_concurrent_agents(self, user_token: str | None = None, raw_token: str | None = None) -> list:
        """Agents used for ConcurrentBuilder — defaults to build_specialist_agents()."""
        return self.build_specialist_agents(user_token, raw_token)

    def build_synthesis_agent(self):
        """Build the synthesis agent that aggregates concurrent specialist results.

        Override in your subclass for a domain-specific synthesis prompt.
        """
        from agent_framework import Agent

        return Agent(
            client=self._client,
            name="synthesis_agent",
            instructions=(
                "You are a senior advisor. Synthesize the specialist responses "
                "below into a coherent, structured, and actionable summary for the user."
            ),
        )

    # ------------------------------------------------------------------
    # Workflow builders (concrete — subclasses should not need to override)
    # ------------------------------------------------------------------

    def _build_handoff_workflow(self, user_token: str | None = None, raw_token: str | None = None):
        """Wire up a HandoffBuilder: triage agent + all specialist agents."""
        from agent_framework.orchestrations import HandoffBuilder

        compaction = self._get_compaction_provider()
        providers: list = [compaction] if compaction else []
        if self._search_provider:
            providers.append(self._search_provider)

        triage = self.build_triage_agent(context_providers=providers or None)
        specialists = self.build_specialist_agents(user_token, raw_token)

        return (
            HandoffBuilder(
                name=self.workflow_name,
                participants=[triage, *specialists],
            )
            .with_start_agent(triage)
            .build()
        )

    def _build_concurrent_workflow(self, user_token: str | None = None, raw_token: str | None = None):
        """Wire up a ConcurrentBuilder: all specialist agents run in parallel,
        then a synthesis agent aggregates the results.
        """
        from agent_framework.orchestrations import ConcurrentBuilder

        specialists = self.build_concurrent_agents(user_token, raw_token)
        synthesis = self.build_synthesis_agent()

        async def _synthesize(results):
            combined = "\n\n".join(
                f"[{(r.agent_response.messages[-1].author_name if r.agent_response.messages else None) or r.executor_id or 'agent'}]\n"
                + (r.agent_response.text or "")
                for r in results
                if r.agent_response
            )
            response = await synthesis.run(combined)
            return "\n".join(m.text for m in response.messages if m.text)

        return (
            ConcurrentBuilder(participants=specialists)
            .with_aggregator(_synthesize)
            .build()
        )

    # ------------------------------------------------------------------
    # Public streaming API
    # ------------------------------------------------------------------

    @staticmethod
    def _build_run_input(message: str, history: list[dict] | None):
        """Convert prior message history + current message into a Message list.

        When history is supplied the workflow sees the full conversation so
        follow-up questions retain context from previous turns.
        """
        from agent_framework import Message

        if not history:
            return message

        msgs: list[Message] = []
        for m in history[-20:]:  # cap to last 20 messages to avoid token overflow
            role = m.get("role", "user")
            content = m.get("content", "")
            if content:
                msgs.append(Message(role, [content]))
        msgs.append(Message("user", [message]))
        return msgs

    async def run_handoff(
        self,
        message: str,
        session_id: str,
        user_token: str | None = None,
        history: list[dict] | None = None,
        raw_token: str | None = None,
    ) -> AsyncIterator[dict]:
        """Stream events from the handoff workflow.

        Args:
            user_token: Stable user identifier (email/oid) for session + dev RLS.
            raw_token:  Raw Entra Bearer string for OBO exchange to downstream MCPs.
        """
        workflow = self._build_handoff_workflow(user_token=user_token, raw_token=raw_token)

        # Buffer triage tokens so we can inspect for the comprehensive trigger
        # without prematurely emitting partial text to the client.
        triage_buffer: list[dict] = []
        triage_text = ""
        handoff_seen = False

        run_input = self._build_run_input(message, history)
        try:
            async with asyncio.timeout(_WORKFLOW_TIMEOUT_SECS):
                async for event in workflow.run(run_input, stream=True):
                    async for item in self._process_workflow_event(event):
                        if item.get("type") == "handoff":
                            # Specialist is taking over — flush triage buffer and yield
                            handoff_seen = True
                            for buffered in triage_buffer:
                                yield buffered
                            triage_buffer = []
                            yield item

                        elif item.get("type") == "agent_response" and not handoff_seen:
                            # Still in triage phase — accumulate, do not emit yet
                            triage_text += item.get("content", "")
                            triage_buffer.append(item)

                        else:
                            # Status / error events, or post-handoff specialist tokens
                            yield item

        except asyncio.TimeoutError:
            logger.error(
                "Handoff workflow timed out after %s s (handoff_seen=%s)",
                _WORKFLOW_TIMEOUT_SECS, handoff_seen,
            )
            yield {"type": "error", "message": f"Workflow timed out after {_WORKFLOW_TIMEOUT_SECS}s"}
            return
        except Exception as exc:
            logger.exception("Handoff workflow error: %s", exc)
            yield {"type": "error", "message": str(exc)}
            return

        # Workflow ended with no handoff — triage responded directly
        if self.comprehensive_trigger and self.comprehensive_trigger in triage_text:
            logger.info("Triage triggered comprehensive analysis")
            yield {"type": "status", "state": "comprehensive_analysis"}
            async for event in self.run_comprehensive(message, session_id, user_token, history=history, raw_token=raw_token):
                yield event
        else:
            for buffered in triage_buffer:
                yield buffered

    async def run_comprehensive(
        self,
        message: str,
        session_id: str,
        user_token: str | None = None,
        history: list[dict] | None = None,
        raw_token: str | None = None,
    ) -> AsyncIterator[dict]:
        """Stream events from the concurrent (all-agents-parallel) workflow."""
        workflow = self._build_concurrent_workflow(user_token=user_token, raw_token=raw_token)
        run_input = self._build_run_input(message, history)
        try:
            async with asyncio.timeout(_WORKFLOW_TIMEOUT_SECS):
                async for event in workflow.run(run_input, stream=True):
                    async for item in self._process_workflow_event(event):
                        yield item
        except asyncio.TimeoutError:
            logger.error("Comprehensive workflow timed out after %s s", _WORKFLOW_TIMEOUT_SECS)
            yield {"type": "error", "message": f"Workflow timed out after {_WORKFLOW_TIMEOUT_SECS}s"}
        except Exception as exc:
            logger.exception("Concurrent workflow error: %s", exc)
            yield {"type": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Event translation
    # ------------------------------------------------------------------

    @staticmethod
    async def _process_workflow_event(event) -> AsyncIterator[dict]:
        """Translate agent-framework workflow events to API-friendly dicts.

        Yields dicts with ``type`` in: agent_response, handoff, status, error.
        """
        from agent_framework._workflows._agent_executor import AgentResponseUpdate

        event_type = getattr(event, "type", None)

        if event_type == "data":
            data = event.data
            if isinstance(data, AgentResponseUpdate) and data.text:
                yield {
                    "type": "agent_response",
                    "agent": getattr(data, "author_name", None) or "assistant",
                    "content": data.text,
                }

        elif event_type == "output":
            data = event.data
            if isinstance(data, AgentResponseUpdate) and data.text:
                yield {
                    "type": "agent_response",
                    "agent": getattr(data, "author_name", None) or "assistant",
                    "content": data.text,
                }
            elif isinstance(data, str) and data:
                yield {
                    "type": "agent_response",
                    "agent": "synthesis_agent",
                    "content": data,
                }
            elif hasattr(data, "messages"):
                for msg in data.messages:
                    if msg.text:
                        yield {
                            "type": "agent_response",
                            "agent": msg.author_name or "assistant",
                            "content": msg.text,
                        }
            elif isinstance(data, list):
                # Terminal _full_conversation list — streaming already delivered
                # tokens per-update above; yielding again would duplicate output.
                pass

        elif event_type == "handoff_sent":
            yield {
                "type": "handoff",
                "from_agent": event.data.source,
                "to_agent": event.data.target,
            }

        elif event_type == "status":
            yield {
                "type": "status",
                "state": str(event.state),
            }

        elif event_type == "error":
            yield {"type": "error", "message": str(event.data)}
