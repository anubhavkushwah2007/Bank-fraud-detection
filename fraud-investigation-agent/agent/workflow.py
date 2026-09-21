"""
agent/workflow.py
──────────────────
LangGraph stateful investigation workflow implementing the
8-stage fraud investigation lifecycle.

Nodes:
  1. trigger_node          → Initialise case & validate trigger
  2. investigate_node      → Extract subgraph & graph evidence
  3. gather_evidence_node  → GraphRAG: policy + similar cases
  4. assess_risk_node      → LLM risk & uncertainty quantification
  5. pre_nba_node          → Pre-evidence NBA selection
  6. extra_evidence_node   → Conditional step-up auth / outreach
  7. post_nba_node         → Post-evidence definitive NBA
  8. sar_explainability_node → SAR generation + case summary
  9. update_memory_node    → Persist to graph + vector store

Edges follow the 8-step lifecycle with a conditional loop
back from extra_evidence → assess_risk when uncertainty remains high.
"""
from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from agent.policy_engine import (
    POLICIES,
    check_sar_required,
    select_post_evidence_action,
    select_pre_evidence_action,
)
from agent.sar_generator import generate_sar_draft
from agent.state import (
    AuditEvent,
    CaseStatus,
    EvidenceGatheringResult,
    FraudAgentState,
    FraudTypology,
    GraphEvidence,
    RiskAssessment,
    SubgraphEdge,
    SubgraphNode,
    TriggerEvent,
    new_case_state,
)
from agent.tools import send_customer_sms, trigger_step_up_mfa
from graph.tigergraph_client import get_graph_client
from rag.graph_rag import build_rag_context, extract_subgraph_evidence, retrieve_similar_cases
from rag.memory_store import get_memory_store

logger = logging.getLogger(__name__)

# ─── LangGraph imports ────────────────────────────────────────────────────────
try:
    from langgraph.graph import END, START, StateGraph
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False
    logger.warning("langgraph not installed — workflow will run in sequential mode.")


# ─── LLM Factory ──────────────────────────────────────────────────────────────

def _get_llm():
    """Return the configured LLM, or None for offline/demo mode."""
    try:
        from config import settings
        if settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=settings.LLM_MODEL,
                temperature=settings.LLM_TEMPERATURE,
                api_key=settings.OPENAI_API_KEY,
            )
        elif settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model="claude-3-5-sonnet-20241022",
                temperature=settings.LLM_TEMPERATURE,
                api_key=settings.ANTHROPIC_API_KEY,
            )
        elif settings.LLM_PROVIDER == "google" and settings.GOOGLE_API_KEY:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model="gemini-1.5-pro",
                temperature=settings.LLM_TEMPERATURE,
                google_api_key=settings.GOOGLE_API_KEY,
            )
    except Exception as e:
        logger.warning(f"LLM init failed: {e} — using heuristic mode.")
    return None


# ─── Heuristic Risk Assessment (LLM-free fallback) ────────────────────────────

def _heuristic_risk_assessment(
    trigger: TriggerEvent,
    evidence: Dict[str, Any],
    rag_context: str,
) -> RiskAssessment:
    """
    Rule-based risk assessment when no LLM is configured.
    Combines graph evidence signals with heuristic weights.
    """
    fp = trigger.initial_risk  # Start from initial score
    signals, conflicts = [], []

    # Shared device accounts (strong fraud signal)
    shared_devs = len(evidence.get("shared_device_accounts", []))
    if shared_devs >= 3:
        fp += 0.15
        signals.append(f"Device shared across {shared_devs} accounts (+0.15)")
    elif shared_devs >= 1:
        fp += 0.08
        signals.append(f"Device shared across {shared_devs} account(s) (+0.08)")

    # Proxy/VPN IP
    if evidence.get("ip_proxy_detected"):
        fp += 0.12
        signals.append("Proxy/VPN IP detected (+0.12)")

    # New device
    if evidence.get("new_device_detected"):
        fp += 0.10
        signals.append("New device not previously seen (+0.10)")

    # High velocity
    burst = evidence.get("velocity_burst_score", 0.0)
    if burst > 10:
        fp += 0.15
        signals.append(f"Extreme velocity burst score {burst:.1f} (+0.15)")
    elif burst > 5:
        fp += 0.08
        signals.append(f"High velocity burst score {burst:.1f} (+0.08)")

    # Fraud ring
    ring_size = evidence.get("ring_size", 0)
    if ring_size >= 5:
        fp += 0.20
        signals.append(f"Part of fraud ring with {ring_size} members (+0.20)")
    elif ring_size >= 3:
        fp += 0.10
        signals.append(f"Possible fraud ring with {ring_size} members (+0.10)")

    # Shared IP
    shared_ips = len(evidence.get("shared_ip_accounts", []))
    if shared_ips >= 2:
        fp += 0.07
        signals.append(f"IP shared across {shared_ips} accounts (+0.07)")

    # Conflicting: legit-looking signals
    country = evidence.get("ip_country", "US")
    if country == "US" and not evidence.get("ip_proxy_detected"):
        conflicts.append("IP is domestic and not proxied (reduces suspicion)")
        fp -= 0.03

    fp = max(0.0, min(1.0, fp))

    # Uncertainty: high when signals are mixed or missing key info
    unc = 0.30
    if not evidence.get("ip_proxy_detected") and fp > 0.60:
        unc += 0.15
        conflicts.append("High risk but no proxy — uncertainty raised")
    if shared_devs == 0 and not evidence.get("new_device_detected"):
        unc += 0.10
        conflicts.append("No device sharing — key signal absent")
    if ring_size == 0:
        unc += 0.05
    unc = max(0.0, min(1.0, unc))

    # Typology heuristic — ordered by specificity
    typology = FraudTypology.UNKNOWN
    # ATO: new device + proxy are the clearest markers
    if evidence.get("new_device_detected") and evidence.get("ip_proxy_detected"):
        typology = FraudTypology.ACCOUNT_TAKEOVER
    # Synthetic identity: large ring AND shared devices
    elif ring_size >= 5 and shared_devs >= 3:
        typology = FraudTypology.SYNTHETIC_IDENTITY
    # Smurfing: high velocity burst — key indicator even without ring
    elif burst > 6:
        typology = FraudTypology.SMURFING_VELOCITY
    # CNP ring: ring + shared devices (smaller ring than synthetic)
    elif ring_size >= 3 and shared_devs >= 1:
        typology = FraudTypology.CARD_NOT_PRESENT_RING
    # Bust-out: moderate amount burst, no device sharing
    elif (evidence.get("total_amount", 0) > 10000
          and evidence.get("total_txn_count", 0) >= 3
          and shared_devs == 0
          and not evidence.get("ip_proxy_detected")):
        typology = FraudTypology.BUST_OUT
    # Fallback CNP
    elif ring_size >= 2 and shared_devs >= 1:
        typology = FraudTypology.CARD_NOT_PRESENT_RING

    reasoning = (
        f"Heuristic assessment: initial_risk={trigger.initial_risk:.2f}, "
        f"adjustments=[{', '.join(signals[:3])}], "
        f"final_fp={fp:.2f}, uncertainty={unc:.2f}, typology={typology.value}."
    )

    return RiskAssessment(
        fraud_probability=fp,
        uncertainty_score=unc,
        likely_fraud_type=typology,
        confidence_factors=signals,
        conflicting_signals=conflicts,
        reasoning=reasoning,
    )


def _llm_risk_assessment(
    llm,
    trigger: TriggerEvent,
    evidence: Dict[str, Any],
    rag_context: str,
) -> RiskAssessment:
    """Use LLM to assess risk with structured JSON output."""
    evidence_str = json.dumps(
        {k: v for k, v in evidence.items() if k not in ("nodes", "edges")},
        indent=2, default=str
    )

    prompt = f"""You are an expert fraud analyst AI. Analyse the following case and return a structured JSON risk assessment.

TRIGGER EVENT:
{json.dumps(trigger.dict(), indent=2, default=str)}

GRAPH EVIDENCE:
{evidence_str}

POLICY & TYPOLOGY CONTEXT:
{rag_context[:3000]}

Return ONLY a valid JSON object with exactly these fields:
{{
  "fraud_probability": <float 0.0-1.0>,
  "uncertainty_score": <float 0.0-1.0>,
  "likely_fraud_type": "<CARD_NOT_PRESENT_RING|ACCOUNT_TAKEOVER|BUST_OUT|SYNTHETIC_IDENTITY|SMURFING_VELOCITY|UNKNOWN>",
  "confidence_factors": ["<signal 1>", "<signal 2>", ...],
  "conflicting_signals": ["<conflict 1>", ...],
  "reasoning": "<2-3 sentence explanation>"
}}
"""
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content.strip()
        # Strip markdown code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        data = json.loads(content.strip())
        return RiskAssessment(
            fraud_probability  = float(data.get("fraud_probability", 0.5)),
            uncertainty_score  = float(data.get("uncertainty_score", 0.5)),
            likely_fraud_type  = FraudTypology(data.get("likely_fraud_type", "UNKNOWN")),
            confidence_factors = data.get("confidence_factors", []),
            conflicting_signals = data.get("conflicting_signals", []),
            reasoning          = data.get("reasoning", ""),
        )
    except Exception as e:
        logger.warning(f"LLM risk assessment failed ({e}), falling back to heuristic.")
        return _heuristic_risk_assessment(trigger, evidence, rag_context)


# ============================================================
# Node Functions
# ============================================================

def trigger_node(state: FraudAgentState) -> FraudAgentState:
    """Node 1: Validate trigger and initialise case in TigerGraph."""
    trigger = state["trigger"]
    case_id = state["case_id"]
    logger.info(f"[TRIGGER] Case {case_id} for account {trigger.account_id}")

    # Open case in graph
    client = get_graph_client()
    client.upsert_case(case_id, {
        "status":       "OPEN",
        "initial_risk": trigger.initial_risk,
        "created_at":   datetime.utcnow().isoformat(),
        "assigned_analyst": "SYSTEM",
    })

    audit = AuditEvent(
        stage="TRIGGER",
        event="CASE_OPENED",
        detail=f"Trigger: {trigger.trigger_type.value}, initial_risk={trigger.initial_risk:.2f}, amount=${trigger.amount:,.2f}",
    )
    return {**state, "audit_trail": state.get("audit_trail", []) + [audit]}


def investigate_node(state: FraudAgentState) -> FraudAgentState:
    """Node 2: Extract subgraph evidence from TigerGraph."""
    account_id = state["account_id"]
    case_id    = state["case_id"]
    logger.info(f"[INVESTIGATE] Extracting subgraph for account {account_id}")

    from config import settings
    raw_evidence = extract_subgraph_evidence(account_id, hop_depth=settings.HOP_DEPTH)

    # Map raw dict to GraphEvidence model
    ge = GraphEvidence(
        nodes                  = [SubgraphNode(**n) for n in raw_evidence.get("nodes", [])],
        edges                  = [SubgraphEdge(**e) for e in raw_evidence.get("edges", [])],
        shared_device_accounts = raw_evidence.get("shared_device_accounts", []),
        shared_ip_accounts     = raw_evidence.get("shared_ip_accounts", []),
        shared_card_accounts   = raw_evidence.get("shared_card_accounts", []),
        ip_proxy_detected      = raw_evidence.get("ip_proxy_detected", False),
        ip_country             = raw_evidence.get("ip_country", "US"),
        new_device_detected    = raw_evidence.get("new_device_detected", False),
        velocity_burst_score   = raw_evidence.get("velocity_burst_score", 0.0),
        txn_per_hour           = raw_evidence.get("txn_per_hour", 0.0),
        unique_device_count    = raw_evidence.get("unique_device_count", 0),
        unique_ip_count        = raw_evidence.get("unique_ip_count", 0),
        ring_component_id      = raw_evidence.get("ring_component_id"),
        ring_size              = raw_evidence.get("ring_size", 0),
        subgraph_path_summary  = raw_evidence.get("subgraph_path_summary", ""),
        raw_query_results      = {k: v for k, v in raw_evidence.items()
                                  if k not in ("nodes", "edges")},
    )

    audit = AuditEvent(
        stage="INVESTIGATE",
        event="SUBGRAPH_EXTRACTED",
        detail=(
            f"Nodes={len(ge.nodes)}, Edges={len(ge.edges)}, "
            f"SharedDeviceAccs={len(ge.shared_device_accounts)}, "
            f"RingSize={ge.ring_size}, ProxyIP={ge.ip_proxy_detected}"
        ),
    )
    return {**state, "graph_evidence": ge, "audit_trail": state.get("audit_trail", []) + [audit]}


def gather_evidence_node(state: FraudAgentState) -> FraudAgentState:
    """Node 3: GraphRAG — retrieve policy context and similar cases."""
    account_id = state["account_id"]
    trigger    = state["trigger"]
    ge         = state.get("graph_evidence", GraphEvidence())
    logger.info(f"[GATHER_EVIDENCE] Running GraphRAG for account {account_id}")

    # Pre-fetch similar cases (we'll refine typology after risk assessment)
    similar = retrieve_similar_cases("UNKNOWN", trigger.initial_risk, account_id)

    rag_context = build_rag_context(
        account_id    = account_id,
        typology_hint = "UNKNOWN",
        risk_score    = trigger.initial_risk,
        similar_cases = similar,
    )

    audit = AuditEvent(
        stage="GATHER_EVIDENCE",
        event="RAG_COMPLETE",
        detail=f"Retrieved {len(similar)} similar cases. Policy context built.",
    )
    return {
        **state,
        "rag_context":   rag_context,
        "similar_cases": similar,
        "audit_trail":   state.get("audit_trail", []) + [audit],
    }


def assess_risk_node(state: FraudAgentState) -> FraudAgentState:
    """Node 4: LLM / heuristic risk & uncertainty quantification."""
    trigger    = state["trigger"]
    ge         = state.get("graph_evidence", GraphEvidence())
    rag_ctx    = state.get("rag_context", "")
    logger.info(f"[ASSESS_RISK] Assessing risk for case {state['case_id']}")

    llm = _get_llm()
    evidence_dict = {
        "shared_device_accounts": ge.shared_device_accounts,
        "shared_ip_accounts":     ge.shared_ip_accounts,
        "shared_card_accounts":   ge.shared_card_accounts,
        "ip_proxy_detected":      ge.ip_proxy_detected,
        "ip_country":             ge.ip_country,
        "new_device_detected":    ge.new_device_detected,
        "velocity_burst_score":   ge.velocity_burst_score,
        "txn_per_hour":           ge.txn_per_hour,
        "unique_device_count":    ge.unique_device_count,
        "unique_ip_count":        ge.unique_ip_count,
        "ring_size":              ge.ring_size,
        "ring_component_id":      ge.ring_component_id,
        "total_txn_count":        ge.raw_query_results.get("total_txn_count", 0),
        "total_amount":           ge.raw_query_results.get("total_amount", 0.0),
    }

    if llm:
        risk = _llm_risk_assessment(llm, trigger, evidence_dict, rag_ctx)
    else:
        risk = _heuristic_risk_assessment(trigger, evidence_dict, rag_ctx)

    audit = AuditEvent(
        stage="ASSESS_RISK",
        event="RISK_ASSESSED",
        detail=(
            f"fraud_probability={risk.fraud_probability:.2f}, "
            f"uncertainty={risk.uncertainty_score:.2f}, "
            f"typology={risk.likely_fraud_type.value}"
        ),
    )
    return {
        **state,
        "risk_assessment": risk,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


def pre_nba_node(state: FraudAgentState) -> FraudAgentState:
    """Node 5: Select pre-evidence Next-Best Action."""
    risk = state.get("risk_assessment", RiskAssessment())
    ge   = state.get("graph_evidence", GraphEvidence())
    logger.info(f"[PRE_NBA] Selecting pre-evidence action for case {state['case_id']}")

    pre_action = select_pre_evidence_action(risk, ge)

    audit = AuditEvent(
        stage="PRE_NBA",
        event="PRE_EVIDENCE_ACTION_SELECTED",
        detail=(
            f"action={pre_action.action.value}, "
            f"approval={pre_action.approval_required.value}, "
            f"confidence={pre_action.confidence:.2f}"
        ),
    )
    return {
        **state,
        "pre_evidence_action": pre_action,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


def extra_evidence_node(state: FraudAgentState) -> FraudAgentState:
    """Node 6: Gather additional evidence via step-up auth or customer outreach."""
    risk     = state.get("risk_assessment", RiskAssessment())
    trigger  = state["trigger"]
    ge       = state.get("graph_evidence", GraphEvidence())
    retries  = state.get("evidence_retries", 0)
    logger.info(f"[EXTRA_EVIDENCE] Gathering additional evidence for case {state['case_id']}")

    from config import settings

    # Choose evidence method
    if ge.ip_proxy_detected or ge.new_device_detected:
        # Prefer step-up MFA for new device / proxy scenarios
        result = trigger_step_up_mfa.invoke({
            "account_id":     trigger.account_id,
            "transaction_id": trigger.transaction_id or "TXN_UNKNOWN",
            "method":         "OTP_SMS",
        })
        action_taken = "STEP_UP_MFA"
    else:
        # Customer outreach for high uncertainty without device signals
        result = send_customer_sms.invoke({
            "account_id":     trigger.account_id,
            "transaction_id": trigger.transaction_id or "TXN_UNKNOWN",
            "amount":         trigger.amount,
        })
        action_taken = "CUSTOMER_OUTREACH_SMS"

    # Interpret response to update risk delta
    resp = result.get("response_received") or result.get("risk_signal", "")
    risk_delta = 0.0
    unc_delta  = 0.0

    if resp in ("VERIFIED", "TRANSACTION_RECOGNIZED", "AUTH_OK"):
        risk_delta = -0.20
        unc_delta  = -0.25
    elif resp in ("TRANSACTION_UNRECOGNIZED", "REPORTED_FRAUD", "AUTH_FAILED", "BLOCKED"):
        risk_delta = +0.15
        unc_delta  = -0.30
    elif resp in ("TIMEOUT", "NO_RESPONSE"):
        unc_delta  = -0.10  # some uncertainty reduction from the attempt

    ev_result = EvidenceGatheringResult(
        action_taken      = action_taken,
        response_status   = result.get("response_status", "UNKNOWN"),
        response_received = resp,
        risk_delta        = risk_delta,
        uncertainty_delta = unc_delta,
    )

    # Update risk assessment
    new_fp  = max(0.0, min(1.0, risk.fraud_probability  + risk_delta))
    new_unc = max(0.0, min(1.0, risk.uncertainty_score  + unc_delta))
    updated_risk = RiskAssessment(
        fraud_probability  = new_fp,
        uncertainty_score  = new_unc,
        likely_fraud_type  = risk.likely_fraud_type,
        confidence_factors = risk.confidence_factors + [f"Customer response: {resp}"],
        conflicting_signals = risk.conflicting_signals,
        reasoning          = risk.reasoning + f" After evidence gathering: {resp}.",
    )

    audit = AuditEvent(
        stage="EXTRA_EVIDENCE",
        event="ADDITIONAL_EVIDENCE_GATHERED",
        detail=(
            f"action={action_taken}, response={resp}, "
            f"risk_delta={risk_delta:+.2f}, unc_delta={unc_delta:+.2f}, "
            f"new_fp={new_fp:.2f}, new_unc={new_unc:.2f}"
        ),
    )
    return {
        **state,
        "additional_evidence": ev_result,
        "risk_assessment":     updated_risk,
        "evidence_retries":    retries + 1,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


def post_nba_node(state: FraudAgentState) -> FraudAgentState:
    """Node 7: Select definitive post-evidence Next-Best Action."""
    risk    = state.get("risk_assessment", RiskAssessment())
    ge      = state.get("graph_evidence", GraphEvidence())
    addl_ev = state.get("additional_evidence")
    logger.info(f"[POST_NBA] Selecting post-evidence action for case {state['case_id']}")

    ae_resp = addl_ev.response_received if addl_ev else ""
    post_action = select_post_evidence_action(risk, ge, ae_resp)

    trigger = state["trigger"]
    sar_required, sar_reason = check_sar_required(risk, post_action, trigger.amount)

    audit = AuditEvent(
        stage="POST_NBA",
        event="POST_EVIDENCE_ACTION_SELECTED",
        detail=(
            f"action={post_action.action.value}, "
            f"approval={post_action.approval_required.value}, "
            f"confidence={post_action.confidence:.2f}, "
            f"sar_required={sar_required}"
        ),
    )
    return {
        **state,
        "post_evidence_action": post_action,
        "sar_required":         sar_required,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


def sar_explainability_node(state: FraudAgentState) -> FraudAgentState:
    """Node 8: Generate SAR draft and case summary using LLM or template."""
    case_id  = state["case_id"]
    risk     = state.get("risk_assessment", RiskAssessment())
    ge       = state.get("graph_evidence", GraphEvidence())
    sar_req  = state.get("sar_required", False)
    logger.info(f"[SAR_EXPLAIN] Generating explainability output for case {case_id}")

    # Try LLM-generated narrative
    narrative = None
    llm = _get_llm()
    if llm and sar_req:
        try:
            prompt = f"""You are a compliance officer drafting a SAR narrative.

Case ID: {case_id}
Account: {state.get('account_id')}
Fraud Typology: {risk.likely_fraud_type.value}
Fraud Probability: {risk.fraud_probability:.0%}
Key Evidence: {', '.join(risk.confidence_factors[:5])}
Subgraph: {ge.subgraph_path_summary}
Pre-Evidence Action: {state.get('pre_evidence_action', {}).action.value if state.get('pre_evidence_action') else 'N/A'}
Post-Evidence Action: {state.get('post_evidence_action', {}).action.value if state.get('post_evidence_action') else 'N/A'}

Write a professional 3-paragraph FinCEN SAR narrative. Be specific and factual."""
            resp = llm.invoke([HumanMessage(content=prompt)])
            narrative = resp.content.strip()
        except Exception as e:
            logger.warning(f"LLM SAR narrative failed: {e}")

    # Generate SAR draft
    sar_draft = generate_sar_draft(state, narrative=narrative) if sar_req else None

    # Build case summary
    pre_act  = state.get("pre_evidence_action")
    post_act = state.get("post_evidence_action")
    addl_ev  = state.get("additional_evidence")

    summary = (
        f"CASE {case_id} INVESTIGATION SUMMARY\n"
        f"{'='*50}\n"
        f"Account:          {state.get('account_id')}\n"
        f"Fraud Probability:{risk.fraud_probability:.0%}\n"
        f"Uncertainty:      {risk.uncertainty_score:.0%}\n"
        f"Typology:         {risk.likely_fraud_type.value}\n\n"
        f"PRE-EVIDENCE ACTION: {pre_act.action.value if pre_act else 'N/A'}\n"
        f"  Justification: {pre_act.justification if pre_act else ''}\n\n"
        f"ADDITIONAL EVIDENCE: {addl_ev.action_taken if addl_ev else 'None'}\n"
        f"  Response: {addl_ev.response_received if addl_ev else 'N/A'}\n\n"
        f"POST-EVIDENCE ACTION: {post_act.action.value if post_act else 'N/A'}\n"
        f"  Approval Required: {post_act.approval_required.value if post_act else 'N/A'}\n"
        f"  Justification: {post_act.justification if post_act else ''}\n\n"
        f"GRAPH EVIDENCE:\n"
        f"  Shared Device Accounts: {len(ge.shared_device_accounts)}\n"
        f"  Proxy IP: {ge.ip_proxy_detected}\n"
        f"  Ring Size: {ge.ring_size}\n"
        f"  Subgraph: {ge.subgraph_path_summary}\n\n"
        f"SAR REQUIRED: {'YES' if sar_req else 'NO'}\n"
        f"\nREASONING: {risk.reasoning}"
    )

    audit = AuditEvent(
        stage="SAR_EXPLAIN",
        event="CASE_SUMMARY_GENERATED",
        detail=f"sar_generated={sar_req}, summary_length={len(summary)} chars",
    )
    return {
        **state,
        "case_summary": summary,
        "sar_draft":    sar_draft,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


def update_memory_node(state: FraudAgentState) -> FraudAgentState:
    """Node 9: Persist final case to TigerGraph and ChromaDB memory."""
    case_id = state["case_id"]
    risk    = state.get("risk_assessment", RiskAssessment())
    post    = state.get("post_evidence_action")
    logger.info(f"[UPDATE_MEMORY] Persisting case {case_id}")

    # Update TigerGraph case record
    client = get_graph_client()
    client.upsert_case(case_id, {
        "status":              "CLOSED",
        "final_risk":          risk.fraud_probability,
        "uncertainty_score":   risk.uncertainty_score,
        "fraud_typology":      risk.likely_fraud_type.value,
        "post_evidence_action": post.action.value if post else "",
        "sar_required":        state.get("sar_required", False),
        "closed_at":           datetime.utcnow().isoformat(),
    })

    # Save to ChromaDB memory
    from agent.state import state_to_result_dict
    memory = get_memory_store()
    state_dict = state_to_result_dict(state)
    # Add extra fields needed by memory store
    state_dict["risk_assessment"] = risk
    state_dict["graph_evidence"]  = state.get("graph_evidence", GraphEvidence())
    state_dict["post_evidence_action"] = post
    memory.save_case(case_id, state)  # type: ignore[arg-type]

    final_status = CaseStatus.CLOSED
    if post and post.action.value in ("ESCALATE_TO_ANALYST",):
        final_status = CaseStatus.ESCALATED

    audit = AuditEvent(
        stage="UPDATE_MEMORY",
        event="CASE_CLOSED",
        detail=f"Persisted to TigerGraph + ChromaDB. Final status: {final_status.value}",
    )
    return {
        **state,
        "case_status": final_status,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


# ============================================================
# Conditional Edge Routing
# ============================================================

def route_after_risk(state: FraudAgentState) -> str:
    """After risk assessment: route to pre-NBA, then check if extra evidence needed."""
    return "pre_nba"


def route_after_pre_nba(state: FraudAgentState) -> str:
    """Decide whether to gather extra evidence or jump to post-NBA."""
    from config import settings
    risk    = state.get("risk_assessment", RiskAssessment())
    retries = state.get("evidence_retries", 0)

    if (risk.uncertainty_score > settings.UNCERTAINTY_THRESHOLD
            and retries < settings.MAX_EVIDENCE_RETRIES):
        return "extra_evidence"
    return "post_nba"


def route_after_extra_evidence(state: FraudAgentState) -> str:
    """After extra evidence: re-assess uncertainty, loop or proceed."""
    from config import settings
    risk    = state.get("risk_assessment", RiskAssessment())
    retries = state.get("evidence_retries", 0)

    if (risk.uncertainty_score > settings.UNCERTAINTY_THRESHOLD
            and retries < settings.MAX_EVIDENCE_RETRIES):
        return "assess_risk"  # Loop back for re-assessment
    return "post_nba"


# ============================================================
# Graph Assembly
# ============================================================

def build_workflow() -> Any:
    """
    Assemble and compile the LangGraph state machine.
    Falls back to a simple sequential runner if LangGraph is unavailable.
    """
    if not _LANGGRAPH_AVAILABLE:
        logger.warning("LangGraph unavailable — returning sequential runner.")
        return _SequentialRunner()

    graph = StateGraph(FraudAgentState)

    # Add nodes
    graph.add_node("trigger",           trigger_node)
    graph.add_node("investigate",       investigate_node)
    graph.add_node("gather_evidence",   gather_evidence_node)
    graph.add_node("assess_risk",       assess_risk_node)
    graph.add_node("pre_nba",           pre_nba_node)
    graph.add_node("extra_evidence",    extra_evidence_node)
    graph.add_node("post_nba",          post_nba_node)
    graph.add_node("sar_explainability", sar_explainability_node)
    graph.add_node("update_memory",     update_memory_node)

    # Add edges
    graph.add_edge(START, "trigger")
    graph.add_edge("trigger",         "investigate")
    graph.add_edge("investigate",     "gather_evidence")
    graph.add_edge("gather_evidence", "assess_risk")
    graph.add_edge("assess_risk",     "pre_nba")

    # Conditional: need extra evidence?
    graph.add_conditional_edges(
        "pre_nba",
        route_after_pre_nba,
        {"extra_evidence": "extra_evidence", "post_nba": "post_nba"},
    )
    # Conditional: loop back for re-assessment or proceed?
    graph.add_conditional_edges(
        "extra_evidence",
        route_after_extra_evidence,
        {"assess_risk": "assess_risk", "post_nba": "post_nba"},
    )

    graph.add_edge("post_nba",          "sar_explainability")
    graph.add_edge("sar_explainability", "update_memory")
    graph.add_edge("update_memory",     END)

    return graph.compile()


# ─── Sequential runner fallback ──────────────────────────────────────────────

class _SequentialRunner:
    """Runs all nodes in order when LangGraph is not installed."""

    def invoke(self, initial_state: FraudAgentState) -> FraudAgentState:
        from config import settings
        state = initial_state
        nodes = [
            trigger_node,
            investigate_node,
            gather_evidence_node,
            assess_risk_node,
            pre_nba_node,
        ]
        for node in nodes:
            state = node(state)

        # Handle evidence loop
        retries = 0
        while (
            state.get("risk_assessment", RiskAssessment()).uncertainty_score
            > settings.UNCERTAINTY_THRESHOLD
            and retries < settings.MAX_EVIDENCE_RETRIES
        ):
            state = extra_evidence_node(state)
            state = assess_risk_node(state)
            retries += 1

        for node in [post_nba_node, sar_explainability_node, update_memory_node]:
            state = node(state)
        return state


# ─── Convenience runner ────────────────────────────────────────────────────────

def run_investigation(trigger: TriggerEvent) -> FraudAgentState:
    """
    Run the complete fraud investigation workflow for a trigger event.

    Args:
        trigger: TriggerEvent initiating the investigation.

    Returns:
        Final FraudAgentState with all results populated.
    """
    initial_state = new_case_state(trigger)
    workflow      = build_workflow()
    final_state   = workflow.invoke(initial_state)
    return final_state
