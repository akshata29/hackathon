# ============================================================
# Agent package init — triggers automatic registry population.
#
# Importing this package causes every agent module to be loaded,
# which fires BaseAgent.__init_subclass__ for each class definition
# and adds it to BaseAgent._registry.
#
# The orchestrator calls `import app.agents` once at workflow-build time
# to ensure all agents are registered before calling
# BaseAgent.registered_agents().
#
# HOW TO ADD A NEW AGENT
# ----------------------
# 1. Create  app/agents/my_agent.py  extending BaseAgent
#    - Set name, description, system_message class vars
#    - Implement build_tools(**kwargs) or override create()
#    - Implement create_from_context(ctx)  ← required for registry loop
# 2. Add the import below — it will be discovered automatically by the
#    orchestrator's build_specialist_agents() without any other changes.
#
# HOW TO ADD AN A2A REMOTE AGENT
# -------------------------------
# 1. Build your A2A server in a2a-agents/<my-agent>/server.py
# 2. Create app/agents/my_a2a_agent.py that returns an A2AAgent in
#    create_from_context() — see app/agents/esg_advisor.py as reference
# 3. Add the import below
# 4. Set MY_A2A_SERVICE_URL in .env
# ============================================================

from app.agents import (  # noqa: F401
    agent_a,
    # TODO: add imports for every agent you create, e.g.:
    # agent_b,
    # my_a2a_agent,
)
