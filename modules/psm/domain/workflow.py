"""State rules for the PSM lifecycle. Policy values are supplied by configuration."""

from enum import StrEnum


class IndentStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    STOCK_RESERVED = "stock_reserved"
    INTERNAL_ISSUE = "internal_issue"
    DEPARTMENT_REVIEW = "department_review"
    HEAD_REVIEW = "head_review"
    PROCUREMENT_REVIEW = "procurement_review"
    FINAL_APPROVAL = "final_approval"
    PROCUREMENT_AUTHORIZED = "procurement_authorized"
    TENDER = "tender"
    PO_ISSUED = "po_issued"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    CANCELLED = "cancelled"


class InvalidTransition(ValueError):
    """Raised when a requested state change is not allowed."""


TRANSITIONS = {
    IndentStatus.DRAFT: {IndentStatus.SUBMITTED, IndentStatus.CANCELLED},
    IndentStatus.SUBMITTED: {
        IndentStatus.STOCK_RESERVED,
        IndentStatus.INTERNAL_ISSUE,
        IndentStatus.DEPARTMENT_REVIEW,
        IndentStatus.WITHDRAWN,
        IndentStatus.CANCELLED,
        IndentStatus.REJECTED,
    },
    IndentStatus.STOCK_RESERVED: {IndentStatus.INTERNAL_ISSUE, IndentStatus.WITHDRAWN},
    IndentStatus.INTERNAL_ISSUE: {IndentStatus.RECEIVED},
    IndentStatus.DEPARTMENT_REVIEW: {
        IndentStatus.HEAD_REVIEW,
        IndentStatus.PROCUREMENT_REVIEW,
        IndentStatus.REJECTED,
        IndentStatus.WITHDRAWN,
    },
    IndentStatus.HEAD_REVIEW: {
        IndentStatus.PROCUREMENT_REVIEW,
        IndentStatus.REJECTED,
        IndentStatus.WITHDRAWN,
    },
    IndentStatus.PROCUREMENT_REVIEW: {
        IndentStatus.FINAL_APPROVAL,
        IndentStatus.PROCUREMENT_AUTHORIZED,
        IndentStatus.TENDER,
        IndentStatus.REJECTED,
    },
    IndentStatus.FINAL_APPROVAL: {IndentStatus.PROCUREMENT_AUTHORIZED, IndentStatus.REJECTED},
    IndentStatus.PROCUREMENT_AUTHORIZED: {IndentStatus.TENDER, IndentStatus.PO_ISSUED},
    IndentStatus.TENDER: {IndentStatus.PO_ISSUED, IndentStatus.REJECTED},
    IndentStatus.PO_ISSUED: {IndentStatus.PARTIALLY_RECEIVED, IndentStatus.RECEIVED},
    IndentStatus.PARTIALLY_RECEIVED: {IndentStatus.PARTIALLY_RECEIVED, IndentStatus.RECEIVED},
}


def validate_transition(current: str, target: str, *, reason: str = "") -> None:
    """Validate a transition and enforce the specified rejection rationale."""
    allowed = TRANSITIONS.get(IndentStatus(current), set())
    destination = IndentStatus(target)
    if destination not in allowed:
        raise InvalidTransition(f"Cannot move an indent from {current} to {target}.")
    if destination is IndentStatus.REJECTED and not reason.strip():
        raise InvalidTransition("A rejection justification is required.")


def procurement_method(amount, *, tender_threshold):
    """Return a configured method; never silently invent a tender threshold."""
    if tender_threshold is None:
        raise ValueError("Configure the tender threshold before routing procurement.")
    return "tender" if amount >= tender_threshold else "direct"
