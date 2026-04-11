# ============================================================
# app.core — Base infrastructure services
#
# These modules are USE-CASE AGNOSTIC. They wire together
# authentication, observability, session management, guardrails,
# and generic HTTP routes. Do not add domain-specific logic here.
#
# When building a new use-case from the template:
#   1. Copy this entire core/ directory into your backend/app/core/
#   2. Define Settings in your app/config.py  (see template/backend/app/config.py)
#   3. Import from app.core.* in your main.py and domain routes
# ============================================================
