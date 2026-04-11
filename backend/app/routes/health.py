# ============================================================
# Health check routes
# ============================================================

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str
    foundry_endpoint: str


@router.get("/health", response_model=HealthResponse)
async def health():
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        foundry_endpoint=settings.foundry_project_endpoint,
    )
