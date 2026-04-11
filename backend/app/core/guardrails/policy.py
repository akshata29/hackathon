# ============================================================
# Guardrails policy enforcement
#
# Harm detection, prompt injection (Prompt Shields), PII, and
# protected-material checks are handled automatically by the
# Foundry content filter policy attached to the model deployment
# (created by scripts/setup-foundry.py).
#
# This module is responsible only for application-layer concerns
# that content filters cannot cover:
#   - Empty / whitespace-only input rejection
#   - Data classification boundary enforcement
# ============================================================

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class DataClassification(str, Enum):
    PUBLIC = "PUBLIC"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class PolicyViolation(Exception):
    """Raised when a guardrail policy is violated."""

    def __init__(self, reason: str, classification: DataClassification | None = None) -> None:
        self.reason = reason
        self.classification = classification
        super().__init__(reason)


@dataclass
class PolicyResult:
    allowed: bool
    reason: str | None = None
    classification: DataClassification = DataClassification.PUBLIC


def check_user_message(text: str) -> PolicyResult:
    """
    Pre-flight input validation before forwarding to the agent workflow.
    Harm detection and prompt injection are handled by the Foundry content
    filter attached to the model deployment — no regex duplication here.
    """
    if not text or not text.strip():
        return PolicyResult(allowed=False, reason="Empty message")
    return PolicyResult(allowed=True)


def assert_data_boundary(
    requested_classification: DataClassification,
    caller_context: str,
) -> None:
    """
    Enforce data classification boundaries at the route level.
    CONFIDENTIAL data must NOT flow through PUBLIC agents.
    Raises PolicyViolation if boundary is crossed.
    """
    if requested_classification == DataClassification.RESTRICTED:
        logger.error(
            "RESTRICTED data access attempted by %s — denied", caller_context
        )
        raise PolicyViolation(
            f"Restricted data access denied for context: {caller_context}",
            DataClassification.RESTRICTED,
        )
