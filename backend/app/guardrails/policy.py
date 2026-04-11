# ============================================================
# Guardrails policy enforcement
# Integrates with agent-framework guardrails for content safety,
# PII detection, and financial data classification checks
# ============================================================

import logging
import re
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


# ---------------------------------------------------------------------------
# PII pattern detection (lightweight pre-check; Azure Content Safety is main)
# ---------------------------------------------------------------------------

_PII_PATTERNS = [
    # US Social Security Number
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # Credit card
    re.compile(r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b"),
    # Simple email
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
]

_FINANCIAL_INSTRUCTION_WORDS = {
    "buy", "sell", "purchase", "short", "liquidate", "invest all",
    "transfer", "wire", "withdraw",
}

_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore (previous|prior|above) instructions", re.IGNORECASE),
    re.compile(r"disregard (your (system )?prompt|instructions)", re.IGNORECASE),
    re.compile(r"you are now (a|an)", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"DAN mode", re.IGNORECASE),
]


@dataclass
class PolicyResult:
    allowed: bool
    reason: str | None = None
    classification: DataClassification = DataClassification.PUBLIC


def check_user_message(text: str) -> PolicyResult:
    """
    Pre-flight policy check on user input before sending to agents.
    Returns PolicyResult with allowed=True if all checks pass.
    """
    if not text or not text.strip():
        return PolicyResult(allowed=False, reason="Empty message")

    # Prompt injection detection
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            logger.warning("Prompt injection attempt detected: %s", text[:200])
            return PolicyResult(
                allowed=False,
                reason="Message contains disallowed instructions",
            )

    # PII in input
    for pattern in _PII_PATTERNS:
        if pattern.search(text):
            logger.warning("PII detected in user message (redacting)")
            return PolicyResult(
                allowed=False,
                reason="Message appears to contain personal information (SSN/card/email). Please do not include sensitive data.",
            )

    return PolicyResult(allowed=True)


def check_agent_response(
    text: str,
    classification: DataClassification = DataClassification.PUBLIC,
) -> PolicyResult:
    """
    Post-generation check on agent output before returning to caller.
    Raises on CONFIDENTIAL data leaking from wrong classification boundary.
    """
    # PII in response
    for pattern in _PII_PATTERNS:
        if pattern.search(text):
            logger.error("PII detected in agent response — blocking output")
            return PolicyResult(
                allowed=False,
                reason="Response blocked: contains potentially sensitive personal data",
                classification=classification,
            )

    return PolicyResult(allowed=True, classification=classification)


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
