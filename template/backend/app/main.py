# ============================================================
# FastAPI application entry point — TEMPLATE VERSION
#
# CORE routes (app.core.routes) → never modify, work for any use-case
# DOMAIN routes (app.routes)    → implement for your use-case
#
# To add a new domain route:
#   1. Create app/routes/my_route.py
#   2. Import and mount it with app.include_router() below
#   See: template/docs/coding-prompts/README.md > Step 3
# ============================================================

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.config import get_settings
from app.core.observability.setup import configure_observability
from app.core.routes import health, sessions
from app.routes import chat, github_auth
# TODO: import your domain routes
# from app.routes import domain

# Configure observability BEFORE creating routes
configure_observability()

settings = get_settings()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="My App API",                          # TODO: rename
    description="Multi-agent platform powered by Microsoft Foundry Agent Framework",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — restrict to the configured frontend origin(s).
# allow_origins=["*"] with allow_credentials=True is rejected by browsers per spec.
_cors_origins: list[str] = [settings.frontend_url] if settings.frontend_url else ["http://localhost:5173"]
if settings.allowed_cors_origins:
    _cors_origins.extend(
        o.strip() for o in settings.allowed_cors_origins.split(",") if o.strip()
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
)

# ── Core routes (do not remove) ────────────────────────────────────────────
app.include_router(health.router, tags=["health"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])

# ── Domain routes (add yours here) ─────────────────────────────────────────
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(github_auth.router, prefix="/api/auth", tags=["auth"])
# TODO: mount your domain routes, e.g.:
# app.include_router(domain.router, prefix="/api/domain", tags=["domain"])


@app.on_event("startup")
async def startup_event():
    logger.info("API starting up — Foundry endpoint: %s", settings.foundry_project_endpoint)
