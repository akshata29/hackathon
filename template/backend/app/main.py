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
from app.routes import chat
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

# CORS — in production, replace * with specific frontend hostnames
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Core routes (do not remove) ────────────────────────────────────────────
app.include_router(health.router, tags=["health"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])

# ── Domain routes (add yours here) ─────────────────────────────────────────
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
# TODO: mount your domain routes, e.g.:
# app.include_router(domain.router, prefix="/api/domain", tags=["domain"])


@app.on_event("startup")
async def startup_event():
    logger.info("API starting up — Foundry endpoint: %s", settings.foundry_project_endpoint)
