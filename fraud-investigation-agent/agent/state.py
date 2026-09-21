"""
agent/state.py
──────────────
Pydantic models and LangGraph TypedDict state definitions
for the HHGOA Fraud Investigation Agent.

FraudAgentState is the single shared state object passed
through all 8 stages of the investigation lifecycle.
"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ============================================================
# Enums
# ============================================================

class FraudTypology(str, Enum):
    CARD_NOT_PRESENT_RING = "CARD_NOT_PRESENT_RING"
    ACCOUNT_TAKEOVER      = "ACCOUNT_TAKEOVER"
    BUST_OUT              = "BUST_OUT"
    SYNTHETIC_IDENTITY    = "SYNTHETIC_IDENTITY"
    SMURFING_VELOCITY     = "SMURFING_VELOCITY"
    UNKNOWN               = "UNKNOWN"


class InvestigationAction(str, Enum):
    ALLOW_TRANSACTION  = "ALLOW_TRANSACTION"
    ADD_TO_WATCHLIST   = "ADD_TO_WATCHLIST"
    BLOCK_TRANSACTION  = "BLOCK_TRANSACTION"
    STEP_UP_AUTH       = "STEP_UP_AUTH"
    FREEZE_ACCOUNT     = "FREEZE_ACCOUNT"
    ACCOUNT_HOLD       = "ACCOUNT_HOLD"
    FILE_SAR           = "FILE_SAR"
    ESCALATE_TO_ANALYST = "ESCALATE_TO_ANALYST"


class ApprovalTier(str, Enum):
    AUTOMATED_POLICY   = "AUTOMATED_POLICY"
    TIER_1_ANALYST     = "TIER_1_ANALYST"
    TIER_2_ANALYST     = "TIER_2_ANALYST"
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"


class CaseStatus(str, Enum):
    OPEN       = "OPEN"
    IN_REVIEW  = "IN_REVIEW"
    ESCALATED  = "ESCALATED"
    CLOSED     = "CLOSED"


class TriggerType(str, Enum):
    HIGH_RISK_SCORE    = "HIGH_RISK_SCORE"
    VELOCITY_SPIKE     = "VELOCITY_SPIKE"
    CUSTOMER_DISPUTE   = "CUSTOMER_DISPUTE"
    ANALYST_INITIATED  = "ANALYST_INITIATED"
    PATTERN_MATCH      = "PATTERN_MATCH"


# ============================================================
# Sub-models
# ============================================================

class TriggerEvent(BaseModel):
    """Initial trigger that starts an investigation."""
    case_id:       str
    account_id:    str
    transaction_id: Optional[str] = None
    trigger_type:  TriggerType
    initial_risk:  float = Field(ge=0.0, le=1.0)
    amount:        float = 0.0
    timestamp:     str   = Field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata:      Dict[str, Any] = Field(default_factory=dict)


class SubgraphNode(BaseModel):
    """A vertex in the extracted neighborhood subgraph."""
    node_id:   str
    node_type: str  # Account | Card | Transaction | Device | IP_Address
    attributes: Dict[str, Any] = Field(default_factory=dict)


class SubgraphEdge(BaseModel):
    """An edge in the extracted neighborhood subgraph."""
    source:    str
    target:    str
    edge_type: str
    attributes: Dict[str, Any] = Field(default_factory=dict)


class GraphEvidence(BaseModel):
    """Structured graph evidence collected during investigation."""
    nodes:                      List[SubgraphNode]  = Field(default_factory=list)
    edges:                      List[SubgraphEdge]  = Field(default_factory=list)
    shared_device_accounts:     List[str]           = Field(default_factory=list)
    shared_ip_accounts:         List[str]           = Field(default_factory=list)
    shared_card_accounts:       List[str]           = Field(default_factory=list)
    ip_proxy_detected:          bool                = False
    ip_country:                 str                 = "US"
    new_device_detected:        bool                = False
    velocity_burst_score:       float               = 0.0
    txn_per_hour:               float               = 0.0
    unique_device_count:        int                 = 0
    unique_ip_count:            int                 = 0
    ring_component_id:          Optional[str]       = None
    ring_size:                  int                 = 0
    subgraph_path_summary:      str                 = ""
    raw_query_results:          Dict[str, Any]      = Field(default_factory=dict)


class RiskAssessment(BaseModel):
    """Output of the uncertainty & risk engine."""
    fraud_probability:  float = Field(ge=0.0, le=1.0, default=0.0)
    uncertainty_score:  float = Field(ge=0.0, le=1.0, default=0.0)
    likely_fraud_type:  FraudTypology = FraudTypology.UNKNOWN
    confidence_factors: List[str]  = Field(default_factory=list)
    conflicting_signals: List[str] = Field(default_factory=list)
    reasoning:          str        = ""


class EvidenceGatheringResult(BaseModel):
    """Result of an additional evidence action (step-up auth, customer outreach)."""
    action_taken:     str
    response_status:  str  # SUCCESS | TIMEOUT | REFUSED | PENDING
    response_received: str = ""
    response_ts:      str  = Field(default_factory=lambda: datetime.utcnow().isoformat())
    risk_delta:       float = 0.0   # change in fraud_probability after evidence
    uncertainty_delta: float = 0.0  # change in uncertainty after evidence


class ActionRecommendation(BaseModel):
    """A single NBA recommendation with justification."""
    action:           InvestigationAction
    approval_required: ApprovalTier
    confidence:       float = Field(ge=0.0, le=1.0)
    fraud_typology:   FraudTypology = FraudTypology.UNKNOWN
    justification:    str  = ""
    policy_refs:      List[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    """Immutable audit trail entry."""
    stage:      str
    actor:      str  = "AGENT"
    event:      str
    detail:     str  = ""
    timestamp:  str  = Field(default_factory=lambda: datetime.utcnow().isoformat())


# ============================================================
# Main Agent State (LangGraph TypedDict)
# ============================================================

class FraudAgentState(TypedDict, total=False):
    """
    Shared state object for the LangGraph state machine.
    Every node reads from and writes to this single dict.
    """

    # ── Stage 1: Trigger ──────────────────────────────────────────────────────
    trigger:            TriggerEvent

    # ── Stage 2: Subgraph Investigation ───────────────────────────────────────
    case_id:            str
    account_id:         str
    transaction_id:     Optional[str]
    graph_evidence:     GraphEvidence

    # ── Stage 3: GraphRAG Evidence ────────────────────────────────────────────
    rag_context:        str   # retrieved policy/typology text
    similar_cases:      List[Dict[str, Any]]

    # ── Stage 4: Risk & Uncertainty ───────────────────────────────────────────
    risk_assessment:    RiskAssessment

    # ── Stage 5: Additional Evidence (conditional) ────────────────────────────
    additional_evidence: Optional[EvidenceGatheringResult]
    evidence_retries:    int

    # ── Stage 6: Pre-evidence NBA ─────────────────────────────────────────────
    pre_evidence_action: Optional[ActionRecommendation]

    # ── Stage 7: Post-evidence NBA ────────────────────────────────────────────
    post_evidence_action: Optional[ActionRecommendation]

    # ── Stage 8: SAR & Explainability ─────────────────────────────────────────
    case_summary:       str
    sar_required:       bool
    sar_draft:          Optional[str]
    sar_filing_id:      Optional[str]

    # ── Case Memory ───────────────────────────────────────────────────────────
    case_status:        CaseStatus
    audit_trail:        List[AuditEvent]

    # ── Control flow ─────────────────────────────────────────────────────────
    next_node:          Optional[str]
    error:              Optional[str]


# ============================================================
# Helpers
# ============================================================

def new_case_state(trigger: TriggerEvent) -> FraudAgentState:
    """Initialise a fresh FraudAgentState from a trigger event."""
    return FraudAgentState(
        trigger=trigger,
        case_id=trigger.case_id,
        account_id=trigger.account_id,
        transaction_id=trigger.transaction_id,
        graph_evidence=GraphEvidence(),
        rag_context="",
        similar_cases=[],
        risk_assessment=RiskAssessment(),
        additional_evidence=None,
        evidence_retries=0,
        pre_evidence_action=None,
        post_evidence_action=None,
        case_summary="",
        sar_required=False,
        sar_draft=None,
        sar_filing_id=None,
        case_status=CaseStatus.OPEN,
        audit_trail=[],
        next_node=None,
        error=None,
    )


def state_to_result_dict(state: FraudAgentState) -> Dict[str, Any]:
    """Serialise FraudAgentState to the competition benchmark JSON format."""
    trigger = state.get("trigger", {})
    pre     = state.get("pre_evidence_action")
    addl    = state.get("additional_evidence")
    post    = state.get("post_evidence_action")
    ge      = state.get("graph_evidence", GraphEvidence())

    return {
        "case_id":          state.get("case_id", ""),
        "initial_trigger":  trigger.dict() if hasattr(trigger, "dict") else trigger,
        "pre_evidence_recommendation": {
            "action":           pre.action.value if pre else "",
            "approval_required": pre.approval_required.value if pre else "",
            "confidence":       pre.confidence if pre else 0.0,
            "justification":    pre.justification if pre else "",
        },
        "additional_evidence_gathered": {
            "action_taken":     addl.action_taken if addl else "",
            "response_received": addl.response_received if addl else "",
            "response_status":  addl.response_status if addl else "",
        },
        "post_evidence_recommendation": {
            "action":           post.action.value if post else "",
            "approval_required": post.approval_required.value if post else "",
            "confidence":       post.confidence if post else 0.0,
            "fraud_typology":   post.fraud_typology.value if post else "",
            "justification":    post.justification if post else "",
        },
        "graph_evidence": {
            "shared_device_accounts_count": len(ge.shared_device_accounts),
            "shared_ip_accounts_count":     len(ge.shared_ip_accounts),
            "ip_proxy_detected":            ge.ip_proxy_detected,
            "new_device_detected":          ge.new_device_detected,
            "velocity_burst_score":         ge.velocity_burst_score,
            "ring_size":                    ge.ring_size,
            "subgraph_path":                ge.subgraph_path_summary,
        },
        "sar_filing_required": state.get("sar_required", False),
        "sar_draft":           state.get("sar_draft", ""),
        "case_status":         state.get("case_status", CaseStatus.OPEN).value
                               if isinstance(state.get("case_status"), CaseStatus)
                               else state.get("case_status", ""),
        "audit_trail": [
            e.dict() if hasattr(e, "dict") else e
            for e in state.get("audit_trail", [])
        ],
    }
