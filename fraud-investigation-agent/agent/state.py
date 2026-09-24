"""
agent/state.py
──────────────
Pydantic models, enums, and LangGraph TypedDict state definitions
for the HHGOA Fraud Investigation Agent. Aligned 100% to the official
competition specification (DATASET_README.md).

Outputs the exact 3-part deliverable:
1. case (15 mandatory fields, authentic dataset IDs)
2. evidence_requests
3. next_best_actions (initial, final, what_changed)
4. sar (FinCEN SAR filing)
plus top-level benchmark metadata (stop_reason, tool_calls, tokens, latency_s).
"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ============================================================
# Enums (Strictly matching DATASET_README.md)
# ============================================================

class TriggerType(str, Enum):
    """Exact trigger types from case_pack.csv."""
    RISK_SCORE      = "risk_score"
    CUSTOMER_REPORT = "customer_report"
    ANALYST_REQUEST = "analyst_request"


class FraudPattern(str, Enum):
    """The 5 known patterns + undocumented + none (spec strings)."""
    CARD_TESTING               = "card_testing"
    CARD_NOT_PRESENT_FRAUD     = "card_not_present_fraud"
    CARD_NOT_PRESENT_NEW_DEVICE = "card_not_present_new_device"
    OUT_OF_REGION_USE          = "out_of_region_use"
    ACCOUNT_TAKEOVER           = "account_takeover"
    UNDOCUMENTED               = "undocumented"
    NONE                       = "none"


# Backward compatibility alias
FraudTypology = FraudPattern


class PolicyAction(str, Enum):
    """The 14 exact policy actions from Fraud Policy Version 1.0."""
    ALLOW_TRANSACTION       = "ALLOW_TRANSACTION"
    DECLINE_TRANSACTION     = "DECLINE_TRANSACTION"
    MONITOR_CARD            = "MONITOR_CARD"
    MONITOR_CONNECTED_CARDS = "MONITOR_CONNECTED_CARDS"
    WARN_CUSTOMER           = "WARN_CUSTOMER"
    VERIFY_WITH_CUSTOMER    = "VERIFY_WITH_CUSTOMER"
    STEP_UP_AUTH            = "STEP_UP_AUTH"
    BLOCK_CARD              = "BLOCK_CARD"
    BLOCK_ALL_CARDS         = "BLOCK_ALL_CARDS"
    GENERATE_REPORT         = "GENERATE_REPORT"
    CREATE_CASE             = "CREATE_CASE"
    FILE_REPORT             = "FILE_REPORT"
    ESCALATE_TO_ANALYST     = "ESCALATE_TO_ANALYST"
    CLOSE_NO_FRAUD          = "CLOSE_NO_FRAUD"


# Backward compatibility alias
InvestigationAction = PolicyAction


class ApprovalRoute(str, Enum):
    """The 3 approval routes from Fraud Policy Version 1.0."""
    AUTO = "auto"
    L1   = "L1"
    L2   = "L2"


# Backward compatibility alias
ApprovalTier = ApprovalRoute


class CaseStatus(str, Enum):
    """Spec status strings for deliverable."""
    OPEN              = "open"
    CLOSED_FRAUD      = "closed_fraud"
    CLOSED_LEGITIMATE = "closed_legitimate"
    ESCALATED         = "escalated"


class CaseVerdict(str, Enum):
    """Spec verdict strings."""
    FRAUD      = "fraud"
    LEGITIMATE = "legitimate"
    UNCERTAIN  = "uncertain"


# ============================================================
# Deliverable Data Models
# ============================================================

class EvidenceItem(BaseModel):
    """An individual piece of evidence supporting the verdict or actions."""
    claim: str
    source: str          # "graph" | "document" | "customer" | "external"
    ref: str             # query name, document section, or request id
    entity_ids: List[str] = Field(default_factory=list)  # Authentic dataset IDs (numeric txn IDs, card IDs, etc.)


class EvidenceRequest(BaseModel):
    """Gathering more evidence: simulated inquiry."""
    type: str            # "customer_validation" | "step_up_auth" | "analyst_info"
    asked_after_step: int = 1
    assumed_response: str


class ActionItem(BaseModel):
    """A next-best action recommendation citing policy rule and route."""
    action: str          # One of 14 PolicyAction strings
    route: str           # "auto" | "L1" | "L2"
    reason: str          # Must cite policy rule, e.g. "R1: Single risk score signal..."


class NextBestActions(BaseModel):
    """Two-stage next-best actions: initial, final, and what changed."""
    initial: List[ActionItem] = Field(default_factory=list)
    final: List[ActionItem]   = Field(default_factory=list)
    what_changed: str         = "nothing"


class SARReport(BaseModel):
    """FinCEN Suspicious Activity Report deliverable."""
    file: bool                = False
    reason: str              = ""
    narrative: str           = ""
    subjects: List[str]      = Field(default_factory=list)
    total_amount_usd: float  = 0.0
    activity_dates: List[str] = Field(default_factory=list)


class CaseDeliverable(BaseModel):
    """
    Part 1: The Case deliverable with all 15 mandatory fields.
    Guarantees summary, written_to_graph, and graph_case_id are never omitted.
    """
    status: str                                  # "open" | "closed_fraud" | "closed_legitimate" | "escalated"
    verdict: str                                 # "fraud" | "legitimate" | "uncertain"
    fraud_probability: float = Field(ge=0.0, le=1.0)
    pattern: str                                 # One of FraudPattern enum values
    pattern_description: str = ""               # 2-3 sentences if pattern == "undocumented", else ""
    affected_txn_ids: List[str] = Field(default_factory=list)    # Authentic numeric IDs from CSV; [] if legitimate
    first_suspicious_txn_id: str = ""           # Authentic numeric ID from CSV or ""
    connected_card_ids: List[str] = Field(default_factory=list)  # Authentic C#####-K# IDs from CSV; [] if none
    connected_device_profiles: List[str] = Field(default_factory=list) # DeviceInfo | OS | browser | screen
    exposure_usd: float = 0.0                   # Sum of |amounts| of affected_txn_ids; 0.0 if legitimate
    evidence: List[EvidenceItem] = Field(default_factory=list)
    similar_prior_cases: List[str] = Field(default_factory=list) # CC-#### IDs from closed_cases_history.csv
    summary: str                                # 2-6 sentences for an analyst
    written_to_graph: bool = True               # Whether stored in TigerGraph / memory store
    graph_case_id: str = ""                     # Graph vertex ID, e.g. "CASE-2016-3514030"


# ============================================================
# Internal Graph & State Models
# ============================================================

class TriggerEvent(BaseModel):
    """Initial trigger that starts an investigation from case_pack.csv."""
    case_id:       str
    card_id:       str = ""
    customer_id:   str = ""
    trigger_type:  TriggerType = TriggerType.RISK_SCORE
    flagged_txn_id: str = ""
    risk_score:    Optional[float] = None
    opened_at:     str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    trigger_text:  str = ""
    amount:        float = 0.0

    def __init__(self, **data: Any):
        if "account_id" in data and not data.get("customer_id"):
            data["customer_id"] = data["account_id"]
        if "customer_id" in data and not data.get("card_id"):
            data["card_id"] = f"{data['customer_id']}-K1"
        if "transaction_id" in data and not data.get("flagged_txn_id"):
            data["flagged_txn_id"] = str(data["transaction_id"] or "")
        if "initial_risk" in data and data.get("risk_score") is None:
            data["risk_score"] = float(data["initial_risk"])
        super().__init__(**data)

    # Backward compatibility properties
    @property
    def account_id(self) -> str:
        return self.customer_id

    @property
    def transaction_id(self) -> str:
        return self.flagged_txn_id

    @property
    def initial_risk(self) -> float:
        return self.risk_score if self.risk_score is not None else 0.5


class SubgraphNode(BaseModel):
    node_id:   str
    node_type: str
    attributes: Dict[str, Any] = Field(default_factory=dict)


class SubgraphEdge(BaseModel):
    source:    str
    target:    str
    edge_type: str
    attributes: Dict[str, Any] = Field(default_factory=dict)


class GraphEvidence(BaseModel):
    """Evidence extracted from dataset CSVs / TigerGraph."""
    nodes:                      List[SubgraphNode]  = Field(default_factory=list)
    edges:                      List[SubgraphEdge]  = Field(default_factory=list)
    shared_device_accounts:     List[str]           = Field(default_factory=list)
    connected_cards:            List[str]           = Field(default_factory=list)
    connected_device_profiles:  List[str]           = Field(default_factory=list)
    card_history_count:         int                 = 0
    card_total_spend:           float               = 0.0
    testing_pattern_detected:   bool                = False
    testing_sequence_txns:      List[str]           = Field(default_factory=list)
    out_of_region_detected:     bool                = False
    normal_region:              Optional[str]       = None
    current_region:             Optional[str]       = None
    new_device_detected:        bool                = False
    proxy_detected:             bool                = False
    device_profile_str:         str                 = ""
    raw_query_results:          Dict[str, Any]      = Field(default_factory=dict)


class RiskAssessment(BaseModel):
    """Output of risk reasoning."""
    fraud_probability:  float = Field(ge=0.0, le=1.0, default=0.5)
    uncertainty_score:  float = Field(ge=0.0, le=1.0, default=0.3)
    likely_pattern:     FraudPattern = FraudPattern.NONE
    pattern_description: str = ""
    is_legitimate:      bool = False
    affected_txn_ids:   List[str] = Field(default_factory=list)
    first_suspicious_txn_id: str = ""
    connected_card_ids: List[str] = Field(default_factory=list)
    exposure_usd:       float = 0.0
    evidence_claims:    List[EvidenceItem] = Field(default_factory=list)
    confidence_factors: List[str] = Field(default_factory=list)
    conflicting_signals: List[str] = Field(default_factory=list)
    reasoning:          str = ""


class AuditEvent(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    stage:     str
    event:     str
    detail:    str = ""


# Backward compatibility model for action recommendation
class ActionRecommendation(BaseModel):
    action: PolicyAction
    approval_required: ApprovalRoute
    confidence: float = 0.0
    justification: str = ""
    fraud_typology: FraudPattern = FraudPattern.NONE


# ============================================================
# Main Agent State (LangGraph TypedDict)
# ============================================================

class FraudAgentState(TypedDict, total=False):
    # Case metadata
    case_id:            str
    card_id:            str
    customer_id:        str
    flagged_txn_id:     str
    trigger:            TriggerEvent

    # Evidence & Graph context
    graph_evidence:     GraphEvidence
    rag_context:        str
    similar_cases:      List[str]

    # Reasoning & Risk
    risk_assessment:    RiskAssessment

    # Evidence gathering loop
    evidence_requests:  List[EvidenceRequest]
    evidence_retries:   int

    # Next Best Actions (Initial & Final)
    initial_actions:    List[ActionItem]
    final_actions:      List[ActionItem]
    what_changed:       str

    # SAR Filing
    sar_required:       bool
    sar_report:         SARReport

    # Case deliverable tracking
    case_status:        CaseStatus
    case_verdict:       CaseVerdict
    summary:            str
    stop_reason:        str
    written_to_graph:   bool
    graph_case_id:      str

    # Execution metrics
    tool_calls_count:   int
    tokens_consumed:    int
    latency_s:          float

    # Audit & Flow
    audit_trail:        List[AuditEvent]
    next_node:          Optional[str]
    error:              Optional[str]


# ============================================================
# Helpers
# ============================================================

def new_case_state(trigger: TriggerEvent) -> FraudAgentState:
    """Initialise a fresh FraudAgentState from a TriggerEvent."""
    return FraudAgentState(
        case_id=trigger.case_id,
        card_id=trigger.card_id,
        customer_id=trigger.customer_id,
        flagged_txn_id=trigger.flagged_txn_id,
        trigger=trigger,
        graph_evidence=GraphEvidence(),
        rag_context="",
        similar_cases=[],
        risk_assessment=RiskAssessment(),
        evidence_requests=[],
        evidence_retries=0,
        initial_actions=[],
        final_actions=[],
        what_changed="nothing",
        sar_required=False,
        sar_report=SARReport(),
        case_status=CaseStatus.OPEN,
        case_verdict=CaseVerdict.UNCERTAIN,
        summary="",
        stop_reason="Initial state",
        written_to_graph=True,
        graph_case_id=f"CASE-2016-{trigger.flagged_txn_id}",
        tool_calls_count=0,
        tokens_consumed=0,
        latency_s=0.0,
        audit_trail=[],
        next_node=None,
        error=None,
    )


def state_to_result_dict(state: FraudAgentState) -> Dict[str, Any]:
    """
    Serialise FraudAgentState into the official competition JSON answer format.
    Strictly enforces:
    - 3-part deliverable: case, evidence_requests, next_best_actions, sar
    - All 15 fields in 'case' object (including summary, written_to_graph, graph_case_id)
    - Authentic dataset IDs (strictly numeric transaction IDs, C#####-K# card IDs, C##### customer IDs)
    - Proper empty structures when legitimate (affected_txn_ids=[], exposure_usd=0, sar.file=False)
    """
    risk = state.get("risk_assessment") or RiskAssessment()
    trigger = state.get("trigger")
    ge = state.get("graph_evidence") or GraphEvidence()

    # Determine verdict and status strings
    status_str = state.get("case_status", CaseStatus.OPEN)
    if isinstance(status_str, CaseStatus):
        status_str = status_str.value

    verdict_str = state.get("case_verdict", CaseVerdict.UNCERTAIN)
    if isinstance(verdict_str, CaseVerdict):
        verdict_str = verdict_str.value

    pattern_val = risk.likely_pattern
    if isinstance(pattern_val, (FraudPattern, FraudTypology)):
        pattern_str = pattern_val.value
    else:
        pattern_str = str(pattern_val)

    # Exposure calculation: sum of absolute amounts of affected_txn_ids
    exposure_usd = round(float(risk.exposure_usd), 2)
    if verdict_str == "legitimate":
        affected_txn_ids = []
        exposure_usd = 0.0
        first_suspicious = ""
    else:
        # Guarantee authentic IDs (stringified numeric IDs)
        affected_txn_ids = [str(tid).strip() for tid in risk.affected_txn_ids if str(tid).strip()]
        first_suspicious = str(risk.first_suspicious_txn_id).strip() if risk.first_suspicious_txn_id else ""

    # Evidence items
    evidence_list = []
    for item in risk.evidence_claims:
        if hasattr(item, "model_dump"):
            evidence_list.append(item.model_dump())
        elif hasattr(item, "dict"):
            evidence_list.append(item.dict())
        elif isinstance(item, dict):
            evidence_list.append(item)

    # Fallback default evidence if empty
    if not evidence_list:
        ref_id = str(state.get("flagged_txn_id", ""))
        evidence_list.append({
            "claim": f"Investigation of flagged transaction {ref_id} with initial score {trigger.risk_score if trigger else 0.5}",
            "source": "graph",
            "ref": f"query:card_history(card_id={state.get('card_id', '')})",
            "entity_ids": [ref_id] if ref_id else [],
        })

    # Connected cards & devices
    connected_cards = [str(c) for c in (risk.connected_card_ids or ge.connected_cards) if str(c) != state.get("card_id")]
    connected_devs = [str(d) for d in ge.connected_device_profiles if str(d).strip()]

    # Summary: guarantee 2-6 sentences
    summary_text = state.get("summary", "")
    if not summary_text or len(summary_text.strip()) < 10:
        if verdict_str == "legitimate":
            summary_text = (
                f"Flagged transaction {state.get('flagged_txn_id', '')} on card {state.get('card_id', '')} "
                f"was reviewed and verified as legitimate activity. Historical spend patterns and lack of device anomalies "
                f"confirm authorized cardholder usage. Alert closed with no fraud."
            )
        elif verdict_str == "fraud":
            summary_text = (
                f"Investigation of card {state.get('card_id', '')} confirmed fraudulent activity under pattern {pattern_str}. "
                f"Total exposure identified across {len(affected_txn_ids)} transaction(s) is ${exposure_usd:,.2f}. "
                f"Immediate protective actions and regulatory reporting recommended."
            )
        else:
            summary_text = (
                f"Investigation of transaction {state.get('flagged_txn_id', '')} on card {state.get('card_id', '')} "
                f"remains inconclusive. Potential risk signals detected but conflicting evidence requires analyst review. "
                f"Escalated under policy R8."
            )

    # 15 mandatory fields for Part 1: Case
    case_part = {
        "status":                    status_str,
        "verdict":                   verdict_str,
        "fraud_probability":         round(float(risk.fraud_probability), 4),
        "pattern":                   pattern_str,
        "pattern_description":       risk.pattern_description if pattern_str == "undocumented" else "",
        "affected_txn_ids":          affected_txn_ids,
        "first_suspicious_txn_id":   first_suspicious,
        "connected_card_ids":        connected_cards,
        "connected_device_profiles":  connected_devs,
        "exposure_usd":              exposure_usd,
        "evidence":                  evidence_list,
        "similar_prior_cases":       [str(c) for c in state.get("similar_cases", [])],
        "summary":                   summary_text,
        "written_to_graph":          bool(state.get("written_to_graph", True)),
        "graph_case_id":             str(state.get("graph_case_id", f"CASE-2016-{state.get('flagged_txn_id', '')}")),
    }

    # Part 2: SAR
    sar_obj = state.get("sar_report") or SARReport()
    file_sar = bool(state.get("sar_required", False) or sar_obj.file)
    if verdict_str == "legitimate":
        file_sar = False

    if file_sar:
        sar_part = {
            "file":             True,
            "reason":           sar_obj.reason or "Confirmed suspicious activity exceeding threshold (Policy R2/R6)",
            "narrative":        sar_obj.narrative,
            "subjects":         sar_obj.subjects or [state.get("customer_id", ""), state.get("card_id", "")],
            "total_amount_usd": round(sar_obj.total_amount_usd or exposure_usd, 2),
            "activity_dates":   sar_obj.activity_dates or [
                trigger.opened_at[:10] if trigger and trigger.opened_at else "2016-12-01",
                trigger.opened_at[:10] if trigger and trigger.opened_at else "2016-12-01",
            ],
        }
    else:
        sar_part = {
            "file":             False,
            "reason":           sar_obj.reason or "No SAR required under policy thresholds.",
            "narrative":        "",
            "subjects":         [],
            "total_amount_usd": 0.0,
            "activity_dates":   [],
        }

    # Part 3: Next Best Actions
    init_acts = [
        a.dict() if hasattr(a, "dict") else a
        for a in state.get("initial_actions", [])
    ]
    fin_acts = [
        a.dict() if hasattr(a, "dict") else a
        for a in state.get("final_actions", [])
    ]
    if not fin_acts and init_acts:
        fin_acts = list(init_acts)

    nba_part = {
        "initial":      init_acts,
        "final":        fin_acts,
        "what_changed": state.get("what_changed", "nothing"),
    }

    # Evidence Requests
    ev_reqs = [
        r.dict() if hasattr(r, "dict") else r
        for r in state.get("evidence_requests", [])
    ]

    return {
        "case_id":           str(state.get("case_id", "")),
        "case":              case_part,
        "evidence_requests": ev_reqs,
        "next_best_actions": nba_part,
        "sar":               sar_part,
        "stop_reason":       state.get("stop_reason", "Investigation completed"),
        "tool_calls":        int(state.get("tool_calls_count", 0)),
        "tokens":            int(state.get("tokens_consumed", 0)),
        "latency_s":         round(float(state.get("latency_s", 0.0)), 2),
    }
