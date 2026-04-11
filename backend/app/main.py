# ============================================================
# FastAPI application entry point
# Features: CORS, Entra auth middleware, WebSocket chat, health check
#
# CORE routes  (app.core.routes) — generic, unchanged across use-cases
# DOMAIN routes (app.routes)     — portfolio-advisor specific
# ============================================================

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.config import get_settings
from app.core.observability.setup import configure_observability
from app.core.routes import health, sessions
from app.routes import chat, portfolio, github_auth

# Configure observability BEFORE creating routes
# Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/observability
configure_observability()

settings = get_settings()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Portfolio Advisor API",
    description="Multi-agent portfolio advisory platform powered by Microsoft Foundry Agent Framework",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — in production, replace with specific frontend hostnames
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(health.router, tags=["health"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(github_auth.router, prefix="/api/auth", tags=["auth"])


@app.on_event("startup")
async def startup_event():
    logger.info("Portfolio Advisor API starting up")
    logger.info("Foundry endpoint: %s", settings.foundry_project_endpoint)
