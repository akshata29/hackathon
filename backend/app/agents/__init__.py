# ============================================================
# Agent package init — triggers automatic registry population.
#
# Importing this package causes every agent module to be loaded,
# which fires BaseAgent.__init_subclass__ for each class definition
# and adds it to BaseAgent._registry.
#
# The orchestrator calls `import app.agents` once at build time
# to ensure all agents are registered before calling
# BaseAgent.registered_agents().
#
# To add a new agent to the platform:
#   1. Create app/agents/my_agent.py extending BaseAgent
#   2. Implement create_from_context(ctx) on your class
#   3. Add the import below — it will be discovered automatically
# ============================================================

from app.agents import (  # noqa: F401
    economic_data,
    esg_advisor,
    github_intel,
    market_intel,
    portfolio_data,
    private_data,
)
