"""
agent/workflow.py
──────────────────
LangGraph stateful investigation workflow implementing the
8-stage fraud investigation lifecycle, fully aligned to the official
Hacker House Goa IEEE-CIS competition specification (DATASET_README.md).

Lifecycle:
  1. trigger_node          -> Initialize case & validate trigger
  2. investigate_node      -> Extract authentic graph neighborhood & identity evidence
  3. gather_evidence_node  -> Retrieve policy rules & closed cases (CC-xxxx) from memory
  4. assess_risk_node      -> Calibrated risk & pattern assessment (~50% legitimate baseline)
  5. pre_nba_node          -> Formulate initial policy recommendations (R1-R10)
  6. extra_evidence_node   -> Simulate evidence inquiries (customer outreach / analyst info)
  7. post_nba_node         -> Formulate final policy recommendations & what_changed
  8. sar_explainability_node -> Generate FinCEN SAR narrative & analyst summary
  9. update_memory_node    -> Persist case to TigerGraph & memory store
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from agent.llm_client import get_rate_limited_llm
from agent.policy_engine import (
    compute_final_actions,
    compute_initial_actions,
    get_action_route,
    simulate_evidence_request,
)
from agent.sar_generator import generate_sar_report
from agent.state import (
    AuditEvent,
    CaseStatus,
    CaseVerdict,
    EvidenceItem,
    EvidenceRequest,
    FraudAgentState,
    FraudPattern,
    GraphEvidence,
    PolicyAction,
    RiskAssessment,
    TriggerEvent,
    TriggerType,
    new_case_state,
    state_to_result_dict,
)
from graph.tigergraph_client import get_graph_client
from rag.memory_store import get_memory_store

logger = logging.getLogger(__name__)

try:
    from langgraph.graph import END, START, StateGraph
    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False
    END = "__end__"  # type: ignore
    START = "__start__"  # type: ignore
    StateGraph = None  # type: ignore
    logger.warning("langgraph not installed — workflow will run in sequential mode.")


# ============================================================
# Node 1: Trigger Node
# ============================================================

def trigger_node(state: FraudAgentState) -> FraudAgentState:
    """Validate trigger and record opening event."""
    trigger = state["trigger"]
    case_id = state["case_id"]
    logger.info(f"[TRIGGER] Opening case {case_id} for card {trigger.card_id}")
    get_rate_limited_llm().reset_case_tokens()

    client = get_graph_client()

    ok, vid = client.upsert_case({
        "case_id": case_id,
        "status": CaseStatus.OPEN.value,
        "verdict": CaseVerdict.UNCERTAIN.value,
        "fraud_probability": float(trigger.risk_score or 0.5),
        "card_id": trigger.card_id,
        "customer_id": trigger.customer_id,
        "flagged_txn_id": trigger.flagged_txn_id,
        "opened_at": trigger.opened_at,
        "summary": f"Case opened via {trigger.trigger_type.value} trigger for transaction {trigger.flagged_txn_id}.",
    })
    if not ok:
        logger.warning(f"[TRIGGER] Stage 1 write-back failed for {case_id}")

    audit = AuditEvent(
        stage="TRIGGER",
        event="CASE_OPENED",
        detail=f"Trigger: {trigger.trigger_type.value}, score={trigger.risk_score}, flagged_txn={trigger.flagged_txn_id}, graph_saved={ok}",
    )
    return {
        **state,
        "written_to_graph": ok,
        "graph_case_id": vid if ok else "",
        "tool_calls_count": state.get("tool_calls_count", 0) + 1,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


# ============================================================
# Node 2: Investigate Node
# ============================================================

def investigate_node(state: FraudAgentState) -> FraudAgentState:
    """Extract authentic dataset graph evidence: history, device profile, rings."""
    trigger = state["trigger"]
    client = get_graph_client()
    logger.info(f"[INVESTIGATE] Querying graph evidence for card {trigger.card_id}")

    tool_calls = state.get("tool_calls_count", 0)

    # 1. Card history
    card_txns = client.get_card_history(trigger.customer_id, trigger.card_id)
    tool_calls += 1

    # 2. Flagged transaction details & device profile
    flagged_info = client.get_transaction(trigger.flagged_txn_id) or {}
    tool_calls += 1

    dev_profile = flagged_info.get("device_profile", "")
    new_dev = flagged_info.get("id_15") == "New"
    proxy_det = "IP_PROXY" in str(flagged_info.get("id_23", ""))

    # 3. Card testing detection (Policy R5)
    is_testing, testing_txns, testing_exp = client.detect_card_testing(trigger.customer_id, trigger.flagged_txn_id)
    tool_calls += 1

    # 4. Out of region detection (Policy R4)
    is_out_of_reg, normal_reg, curr_reg = client.detect_out_of_region(trigger.customer_id, trigger.flagged_txn_id)
    tool_calls += 1

    # 5. Shared device detection (Policy R6)
    shared_ents = client.detect_shared_entities(trigger.card_id, dev_profile)
    tool_calls += 1

    connected_cards = shared_ents.get("connected_cards", [])
    # Only populate connected_device_profiles if it actually links this case to other cards
    connected_devs = [dev_profile] if (dev_profile and len(connected_cards) > 0) else []

    total_spend = sum(t.get("TransactionAmt", 0.0) for t in card_txns)

    ge = GraphEvidence(
        shared_device_accounts=shared_ents.get("shared_device_accounts", []),
        connected_cards=connected_cards,
        connected_device_profiles=connected_devs,
        card_history_count=len(card_txns),
        card_total_spend=round(total_spend, 2),
        testing_pattern_detected=is_testing,
        testing_sequence_txns=testing_txns,
        out_of_region_detected=is_out_of_reg,
        normal_region=normal_reg,
        current_region=curr_reg,
        new_device_detected=new_dev,
        proxy_detected=proxy_det,
        device_profile_str=dev_profile,
        raw_query_results=flagged_info,
    )

    audit = AuditEvent(
        stage="INVESTIGATE",
        event="GRAPH_EVIDENCE_EXTRACTED",
        detail=f"HistoryTxns={len(card_txns)}, Device={dev_profile[:25]}, ConnectedCards={len(connected_cards)}",
    )
    return {
        **state,
        "graph_evidence": ge,
        "tool_calls_count": tool_calls,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


# ============================================================
# Node 3: Gather Evidence Node
# ============================================================

def gather_evidence_node(state: FraudAgentState) -> FraudAgentState:
    """Retrieve policy context and similar closed cases (CC-xxxx) from memory."""
    trigger = state["trigger"]
    ge = state.get("graph_evidence", GraphEvidence())
    ms = get_memory_store()
    tool_calls = state.get("tool_calls_count", 0)

    # Determine candidate pattern for retrieval
    candidate_pat = "none"
    if ge.testing_pattern_detected:
        candidate_pat = "card_testing"
    elif len(ge.connected_cards) > 0 or trigger.trigger_type == TriggerType.ANALYST_REQUEST:
        candidate_pat = "card_not_present_fraud"
    elif ge.new_device_detected and ge.proxy_detected:
        candidate_pat = "account_takeover"
    elif ge.new_device_detected:
        candidate_pat = "card_not_present_new_device"
    elif ge.out_of_region_detected:
        candidate_pat = "out_of_region_use"

    client = get_graph_client()
    similar_cases_records = client.find_similar_cases(pattern=candidate_pat, amount_band=float(ge.raw_query_results.get("TransactionAmt", 0.0)), top_k=3)
    similar_case_ids = [c["case_id"] for c in similar_cases_records]
    tool_calls += 1

    # Stage 2: Evidence Added
    ok, vid = client.upsert_case({
        "case_id": state["case_id"],
        "status": "evidence_added",
        "verdict": "in_review",
        "card_id": trigger.card_id,
        "customer_id": trigger.customer_id,
        "flagged_txn_id": trigger.flagged_txn_id,
        "connected_card_ids": ge.connected_cards,
        "similar_prior_cases": similar_case_ids,
        "summary": f"Evidence extracted: {len(ge.connected_cards)} connected card(s), {len(similar_case_ids)} matching precedent(s).",
    })

    audit = AuditEvent(
        stage="GATHER_EVIDENCE",
        event="MEMORY_RETRIEVAL_COMPLETE",
        detail=f"Retrieved similar cases: {similar_case_ids}, graph_updated={ok}",
    )
    return {
        **state,
        "similar_cases": similar_case_ids,
        "similar_case_records": similar_cases_records,
        "written_to_graph": ok or state.get("written_to_graph", False),
        "graph_case_id": vid if ok else state.get("graph_case_id", ""),
        "tool_calls_count": tool_calls,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


# ============================================================
# Node 4: Assess Risk Node (Anti-Overflagging Calibrated)
# ============================================================

def assess_risk_node(state: FraudAgentState) -> FraudAgentState:
    """
    Synthesize graph signals into a calibrated fraud probability and pattern
    computed purely from empirical data:
    - Card history spend range (mean, max, ratio)
    - New device (id_15 == "New"), proxy (id_23), shared device rings
    - Billing region vs. card's historical region (Policy R4)
    - Rapid small authorizations before larger purchase (Policy R5)
    - Closed-case memory similarity
    """
    trigger = state["trigger"]
    ge = state.get("graph_evidence", GraphEvidence())
    ms = get_memory_store()
    tool_calls = state.get("tool_calls_count", 0)

    flagged_txn = trigger.flagged_txn_id
    flagged_amt = ge.raw_query_results.get("TransactionAmt", 0.0)
    raw_q = ge.raw_query_results
    card_txns = get_graph_client().get_card_history(trigger.customer_id, trigger.card_id)
    tool_calls += 1

    evidence_claims: List[EvidenceItem] = []

    # 1. Historical card profile metrics
    prior_amts = [t["TransactionAmt"] for t in card_txns if str(t.get("TransactionID")) != str(flagged_txn)]
    n_hist = len(prior_amts)
    mean_amt = (sum(prior_amts) / n_hist) if n_hist > 0 else flagged_amt
    max_amt = max(prior_amts) if n_hist > 0 else flagged_amt
    amt_ratio = (flagged_amt / (mean_amt + 1e-4)) if mean_amt > 0 else 1.0

    # 2. Extract empirical signals from data
    is_new_device = ge.new_device_detected or (raw_q.get("id_15") == "New")
    is_found_device = (raw_q.get("id_15") == "Found")
    is_proxy = ge.proxy_detected
    has_shared_ring = len(ge.connected_cards) > 0
    is_testing = ge.testing_pattern_detected
    is_oor = ge.out_of_region_detected

    # 3. Base Prior logit from risk score or neutral trigger
    # Model score is only one input among many
    if trigger.trigger_type == TriggerType.RISK_SCORE and trigger.risk_score is not None:
        p0 = max(0.05, min(0.95, float(trigger.risk_score)))
        z = math.log(p0 / (1.0 - p0))
    else:
        z = 0.0  # Neutral prior for customer reports and analyst inquiries

    # 4. Evidence-based Log-Odds Adjustments:
    # A. Card History Window & Amount relative to normal range
    if n_hist >= 5:
        if flagged_amt <= mean_amt and flagged_amt <= max_amt:
            z -= 1.8  # Strong legitimate indicator: routine spend well within normal cardholder bounds
            evidence_claims.append(EvidenceItem(
                claim=f"Flagged amount ${flagged_amt:.2f} is well within cardholder historical average of ${mean_amt:.2f} (max ${max_amt:.2f})",
                source="graph",
                ref=f"query:card_history(customer_id={trigger.customer_id})",
                entity_ids=[flagged_txn],
            ))
        elif flagged_amt <= 1.5 * mean_amt and flagged_amt <= max_amt:
            z -= 0.8  # Routine spend
        elif flagged_amt > 2.0 * max_amt or (mean_amt > 0 and amt_ratio > 3.0 and flagged_amt > max_amt):
            z += 2.2  # Massive unprecedented spend spike
            evidence_claims.append(EvidenceItem(
                claim=f"Abnormal spend spike of ${flagged_amt:.2f} ({amt_ratio:.1f}x average, previous max ${max_amt:.2f})",
                source="graph",
                ref=f"query:card_history(customer_id={trigger.customer_id})",
                entity_ids=[flagged_txn],
            ))
        elif mean_amt > 0 and amt_ratio > 2.0:
            z += 1.0

    # B. Device Footprint
    if is_new_device:
        z += 1.5
        evidence_claims.append(EvidenceItem(
            claim=f"Transaction originated from a new unrecognized device profile ({ge.device_profile_str[:40]})",
            source="graph",
            ref=f"query:device_profile(txn_id={flagged_txn})",
            entity_ids=[flagged_txn],
        ))
    elif is_found_device:
        z -= 1.4  # Known cardholder device

    if is_proxy:
        z += 1.8
        evidence_claims.append(EvidenceItem(
            claim="Transaction routed through an anonymizing proxy",
            source="graph",
            ref=f"query:network_attributes(txn_id={flagged_txn})",
            entity_ids=[flagged_txn],
        ))

    # C. Shared Device Ring across cards (computed dynamically from data)
    if has_shared_ring:
        z += 2.8
        evidence_claims.append(EvidenceItem(
            claim=f"Device profile linked across {len(ge.connected_cards)} other card(s) in compromise cluster: {', '.join(ge.connected_cards[:3])}",
            source="graph",
            ref=f"query:shared_entities(card_id={trigger.card_id})",
            entity_ids=ge.connected_cards + [flagged_txn],
        ))

    # D. Billing Region Anomaly (Policy R4)
    if is_oor:
        z += 1.5
        evidence_claims.append(EvidenceItem(
            claim=f"Out-of-region activity detected: billing region {ge.current_region} not present in customer history (modal {ge.normal_region})",
            source="graph",
            ref=f"query:detect_out_of_region(customer_id={trigger.customer_id})",
            entity_ids=[flagged_txn],
        ))
    elif n_hist >= 5 and not is_oor:
        z -= 0.6  # Domestic home billing region consistency

    # E. Rapid Small Authorizations before larger purchase (Policy R5)
    if is_testing:
        z += 3.5
        evidence_claims.append(EvidenceItem(
            claim=f"Card testing sequence confirmed: {len(ge.testing_sequence_txns)-1} micro-authorizations under $5 within 1 hour before purchase",
            source="graph",
            ref=f"query:card_history(customer_id={trigger.customer_id})",
            entity_ids=ge.testing_sequence_txns,
        ))

    # F. Closed-Case Similarity (Memory Store)
    sim_records = state.get("similar_case_records", [])
    if sim_records:
        n_sim = len(sim_records)
        n_fraud = sum(1 for c in sim_records if c.get("outcome") in ("confirmed_fraud", "fraud"))
        n_cleared = sum(1 for c in sim_records if c.get("outcome") in ("cleared", "legitimate"))
        evidence_claims.append(EvidenceItem(
            claim=f"{n_sim} similar closed cases: {n_fraud} confirmed_fraud, {n_cleared} cleared",
            source="memory",
            ref="query:similar_closed_cases",
            entity_ids=[c["case_id"] for c in sim_records],
        ))
        fraud_ratio = n_fraud / n_sim if n_sim > 0 else 0.5
        if fraud_ratio >= 0.70:
            z += 0.4
        elif fraud_ratio <= 0.30:
            z -= 0.4

    # G. LLM Evidence Synthesis: synthesize primary signals into an evidence claim
    try:
        synth_prompt = (
            f"You are a bank fraud investigator. In ONE short, factual sentence, synthesize the following evidence: "
            f"Customer {trigger.customer_id}, Card {trigger.card_id}, amount=${flagged_amt:.2f} ({amt_ratio:.1f}x normal), "
            f"new_device={is_new_device}, proxy={is_proxy}, connected_cards={len(ge.connected_cards)}, "
            f"card_testing={is_testing}, out_of_region={is_oor}. "
            f"State whether this pattern indicates legitimate cardholder activity or unauthorized compromise."
        )
        synth_res = get_rate_limited_llm().invoke(synth_prompt, max_tokens=80, temperature=0.1)
        if synth_res and len(synth_res) > 10:
            evidence_claims.append(EvidenceItem(
                claim=synth_res.strip().replace("\n", " "),
                source="llm_synthesis",
                ref="evidence_synthesis",
                entity_ids=[flagged_txn],
            ))
    except Exception as e:
        logger.debug(f"LLM evidence synthesis error: {e}")

    # 5. Sigmoid Link: compute fraud probability

    fp = 1.0 / (1.0 + math.exp(-z))
    is_legit = (fp < 0.50)

    # Calibrate probability output range for policy engine
    if is_legit:
        fp = min(0.35, max(0.05, fp))
    else:
        fp = min(0.95, max(0.75, fp))

    # 6. Typology classification from evidence
    pattern_desc = ""
    if is_testing:
        pattern = FraudPattern.CARD_TESTING
    elif has_shared_ring and is_new_device:
        pattern = FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE
    elif has_shared_ring and is_proxy:
        pattern = FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE
    elif is_new_device:
        pattern = FraudPattern.CARD_NOT_PRESENT_NEW_DEVICE
    elif is_oor and not is_legit:
        pattern = FraudPattern.OUT_OF_REGION_USE
    elif not is_legit:
        pattern = FraudPattern.CARD_NOT_PRESENT_FRAUD
    else:
        pattern = FraudPattern.NONE

    # Exposure and affected txns
    if is_legit:
        affected_txns = []
        exposure = 0.0
        first_suspicious = ""
    elif is_testing and len(ge.testing_sequence_txns) >= 3:
        affected_txns = ge.testing_sequence_txns
        exposure = sum(
            float(t.get("TransactionAmt", 0.0))
            for t in card_txns
            if str(t.get("TransactionID")) in affected_txns
        ) or flagged_amt
        first_suspicious = affected_txns[0] if affected_txns else flagged_txn
    else:
        affected_txns = [flagged_txn]
        exposure = flagged_amt
        first_suspicious = flagged_txn

    risk = RiskAssessment(
        fraud_probability=round(fp, 4),
        uncertainty_score=0.25 if (fp >= 0.80 or fp <= 0.25) else 0.45,
        likely_pattern=pattern,
        pattern_description=pattern_desc,
        is_legitimate=is_legit,
        affected_txn_ids=affected_txns,
        first_suspicious_txn_id=first_suspicious,
        connected_card_ids=ge.connected_cards,
        exposure_usd=round(exposure, 2),
        evidence_claims=evidence_claims,
        reasoning=f"Evidence-based scoring for card {trigger.card_id} on transaction {trigger.flagged_txn_id}: z={z:+.2f}, fp={fp:.2f}, pattern={pattern.value}.",
    )

    audit = AuditEvent(
        stage="ASSESS_RISK",
        event="RISK_EVALUATED",
        detail=f"fp={fp:.2f}, pattern={pattern.value}, is_legit={is_legit}",
    )
    return {
        **state,
        "risk_assessment": risk,
        "tool_calls_count": tool_calls,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


# ============================================================
# Node 5: Pre-NBA Node
# ============================================================

def pre_nba_node(state: FraudAgentState) -> FraudAgentState:
    """Formulate initial recommendations citing policy rules."""
    trigger = state["trigger"]
    ge = state.get("graph_evidence", GraphEvidence())
    risk = state.get("risk_assessment", RiskAssessment())

    initial_actions = compute_initial_actions(trigger, ge, risk)

    # Stage 3: Initial Recommendation
    client = get_graph_client()
    init_act = initial_actions[0] if initial_actions else None
    ok, vid = client.upsert_case({
        "case_id": state["case_id"],
        "status": "initial_recommendation",
        "verdict": state["case_verdict"].value,
        "fraud_probability": risk.fraud_probability,
        "pattern": risk.likely_pattern.value,
        "exposure_usd": risk.exposure_usd,
        "card_id": trigger.card_id,
        "customer_id": trigger.customer_id,
        "summary": f"Initial recommendation: {init_act.action if init_act else 'NONE'}. Rationale: {init_act.reason if init_act else ''}",
    })

    audit = AuditEvent(
        stage="PRE_NBA",
        event="INITIAL_ACTIONS_FORMULATED",
        detail=f"Initial actions: {[a.action for a in initial_actions]}, graph_updated={ok}",
    )
    return {
        **state,
        "initial_actions": initial_actions,
        "written_to_graph": ok or state.get("written_to_graph", False),
        "graph_case_id": vid if ok else state.get("graph_case_id", ""),
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


# ============================================================
# Node 6: Extra Evidence Node
# ============================================================

def extra_evidence_node(state: FraudAgentState) -> FraudAgentState:
    """Simulate evidence requests (customer validation / analyst info)."""
    trigger = state["trigger"]
    ge = state.get("graph_evidence", GraphEvidence())
    risk = state.get("risk_assessment", RiskAssessment())
    init_acts = state.get("initial_actions", [])

    ev_req = simulate_evidence_request(trigger, init_acts, ge, risk)
    ev_requests = [ev_req] if ev_req else []

    # Stage 4: Evidence Request
    client = get_graph_client()
    ok, vid = client.upsert_case({
        "case_id": state["case_id"],
        "status": "evidence_requested",
        "card_id": trigger.card_id,
        "customer_id": trigger.customer_id,
        "summary": f"Inquiry: {ev_req.type if ev_req else 'None'} -> Response: {ev_req.assumed_response[:40] if ev_req else ''}",
    })

    audit = AuditEvent(
        stage="EXTRA_EVIDENCE",
        event="EVIDENCE_REQUEST_SIMULATED",
        detail=f"Requested: {ev_req.type if ev_req else 'None'}, response: {ev_req.assumed_response[:30] if ev_req else ''}, graph_updated={ok}",
    )
    return {
        **state,
        "evidence_requests": ev_requests,
        "written_to_graph": ok or state.get("written_to_graph", False),
        "graph_case_id": vid if ok else state.get("graph_case_id", ""),
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


# ============================================================
# Node 7: Post-NBA Node
# ============================================================

def post_nba_node(state: FraudAgentState) -> FraudAgentState:
    """Formulate final recommendations, what_changed, and final verdict."""
    trigger = state["trigger"]
    ge = state.get("graph_evidence", GraphEvidence())
    risk = state.get("risk_assessment", RiskAssessment())
    ev_reqs = state.get("evidence_requests", [])
    ev_req = ev_reqs[0] if ev_reqs else None

    final_actions, what_changed, sar_required = compute_final_actions(
        trigger, ge, risk, ev_req, state.get("initial_actions", [])
    )


    # Determine final verdict and status
    has_close_no_fraud = any(a.action == PolicyAction.CLOSE_NO_FRAUD.value for a in final_actions)
    has_block = any(a.action in (PolicyAction.BLOCK_CARD.value, PolicyAction.BLOCK_ALL_CARDS.value) for a in final_actions)

    if has_close_no_fraud:
        verdict = CaseVerdict.LEGITIMATE
        status = CaseStatus.CLOSED_LEGITIMATE
        risk.is_legitimate = True
        risk.affected_txn_ids = []
        risk.exposure_usd = 0.0
        risk.fraud_probability = min(risk.fraud_probability, 0.15)
    elif has_block:
        verdict = CaseVerdict.FRAUD
        status = CaseStatus.CLOSED_FRAUD
        risk.fraud_probability = max(risk.fraud_probability, 0.85)
    else:
        verdict = CaseVerdict.UNCERTAIN
        status = CaseStatus.ESCALATED

    audit = AuditEvent(
        stage="POST_NBA",
        event="FINAL_ACTIONS_FORMULATED",
        detail=f"Final actions: {[a.action for a in final_actions]}, Verdict={verdict.value}",
    )
    return {
        **state,
        "final_actions": final_actions,
        "what_changed": what_changed,
        "sar_required": sar_required,
        "case_verdict": verdict,
        "case_status": status,
        "risk_assessment": risk,
        "audit_trail": state.get("audit_trail", []) + [audit],
    }


def generate_analyst_summary_with_llm(
    trigger: TriggerEvent,
    risk: RiskAssessment,
    evidence: GraphEvidence,
    verdict: CaseVerdict,
    final_actions: List[ActionItem],
) -> str:
    """Generate 2-4 sentence internal analyst summary using LLM."""
    pat_name = risk.likely_pattern.value if hasattr(risk.likely_pattern, "value") else str(risk.likely_pattern)
    prompt = f"""You are a bank fraud investigation specialist writing a concise case summary for a fraud analyst.

FACTS:
- Customer ID: {trigger.customer_id}
- Card ID: {trigger.card_id}
- Flagged Transaction: {trigger.flagged_txn_id}
- Verdict: {verdict.value}
- Pattern: {pat_name}
- Total Exposure: ${risk.exposure_usd:,.2f}
- Affected Transaction IDs: {', '.join(risk.affected_txn_ids) if risk.affected_txn_ids else 'None'}
- Connected Cards: {', '.join(evidence.connected_cards) if evidence.connected_cards else 'None'}
- Final Actions: {', '.join([a.action for a in final_actions])}

INSTRUCTIONS:
Write a concise 2 to 4 sentence executive summary of this investigation.
1. State the final determination and whether the transaction was authorized cardholder spend or confirmed compromise.
2. Highlight key evidence (spend bounds, device profile, customer outreach response, or multi-card linkages).
3. State the concluding actions taken under bank policy (e.g. card blocked for reissue, case cleared, or report filed).

OUTPUT RULES:
- Exactly 2 to 4 sentences in a single paragraph.
- Professional bank compliance tone.
- Do NOT use bullet points or headers.
"""
    try:
        llm = get_rate_limited_llm()
        content = llm.invoke(prompt, max_tokens=250, temperature=0.1)
        sentences = [s.strip() for s in content.split(".") if s.strip()]
        if len(sentences) >= 2:
            return content.strip().replace("\n", " ")
    except Exception as e:
        logger.warning(f"LLM analyst summary generation failed: {e}")

    # Deterministic fallback
    if verdict == CaseVerdict.LEGITIMATE:
        return (
            f"Alert on card {trigger.card_id} for transaction {trigger.flagged_txn_id} was reviewed and cleared. "
            f"Customer verification confirmed the activity was authorized cardholder spend. "
            f"Historical spend consistency in billing region confirms lack of compromise. "
            f"Alert resolved under Policy R3 as closed legitimate with zero exposure."
        )
    elif verdict == CaseVerdict.FRAUD:
        return (
            f"Investigation confirmed fraudulent activity on card {trigger.card_id} under pattern {pat_name}. "
            f"Total exposure of ${risk.exposure_usd:,.2f} identified across {len(risk.affected_txn_ids)} transaction(s). "
            f"Cardholder denial established unauthorized card usage from digital fingerprint. "
            f"Card blocked for reissue and regulatory report filed under Policy R2."
        )
    else:
        return (
            f"Investigation of transaction {trigger.flagged_txn_id} on card {trigger.card_id} yielded ambiguous signals. "
            f"Exposure of ${risk.exposure_usd:,.2f} exceeds threshold without decisive evidence confirmation. "
            f"Case escalated to Level 2 fraud analyst for manual review under Policy R8."
        )


def sar_explainability_node(state: FraudAgentState) -> FraudAgentState:
    """Produce FinCEN SAR draft if FILE_REPORT is required, and 2-6 sentence summary."""
    trigger = state["trigger"]
    risk = state.get("risk_assessment", RiskAssessment())
    ge = state.get("graph_evidence", GraphEvidence())
    fin_acts = state.get("final_actions", [])
    verdict = state.get("case_verdict", CaseVerdict.UNCERTAIN)

    sar_report = generate_sar_report(
        trigger=trigger,
        risk=risk,
        evidence=ge,
        final_actions=fin_acts,
    )

    summary = generate_analyst_summary_with_llm(
        trigger=trigger,
        risk=risk,
        evidence=ge,
        verdict=verdict,
        final_actions=fin_acts,
    )

    # Stop reason
    if verdict == CaseVerdict.LEGITIMATE:
        stop_reason = "Customer confirmation settled the inquiry; further steps unnecessary."
    elif verdict == CaseVerdict.FRAUD:
        stop_reason = "Definitive evidence of compromise obtained; protective actions and report executed."
    else:
        stop_reason = "Uncertainty remains with material exposure; escalation required."

    tokens = 0
    try:
        tokens = get_rate_limited_llm().get_case_tokens()
    except Exception:
        pass

    return {
        **state,
        "sar_report": sar_report,
        "summary": summary,
        "stop_reason": stop_reason,
        "tokens_consumed": tokens,
    }



# ============================================================
# Node 9: Update Memory Node
# ============================================================

def update_memory_node(state: FraudAgentState) -> FraudAgentState:
    """Persist case deliverable to TigerGraph and CaseMemoryStore."""
    case_id = state["case_id"]
    trigger = state["trigger"]
    client = get_graph_client()
    ms = get_memory_store()

    tool_calls = state.get("tool_calls_count", 0)

    # Stage 5: Final Recommendation & Memory Commit
    res_dict = state_to_result_dict(state)
    case_payload = dict(res_dict["case"])
    case_payload["case_id"] = case_id
    case_payload["card_id"] = trigger.card_id
    case_payload["customer_id"] = trigger.customer_id
    ok, vid = client.upsert_case(case_payload)
    if not ok:
        err_msg = f"Failed to persist case {case_id} to TigerGraph"
        logger.error(f"[MEMORY] {err_msg}")
        error_val = state.get("error") or err_msg
    else:
        error_val = state.get("error")


    ms.save_case(case_id, res_dict["case"])
    tool_calls += 2

    return {
        **state,
        "written_to_graph": ok,
        "graph_case_id": vid if ok else "",
        "error": error_val,
        "tool_calls_count": tool_calls,
    }


# ============================================================
# Sequential & LangGraph Runner
# ============================================================

def build_workflow():
    """Build LangGraph StateGraph if available."""
    if not _LANGGRAPH_AVAILABLE or StateGraph is None:
        return None

    graph = StateGraph(FraudAgentState)
    graph.add_node("trigger_node", trigger_node)
    graph.add_node("investigate_node", investigate_node)
    graph.add_node("gather_evidence_node", gather_evidence_node)
    graph.add_node("assess_risk_node", assess_risk_node)
    graph.add_node("pre_nba_node", pre_nba_node)
    graph.add_node("extra_evidence_node", extra_evidence_node)
    graph.add_node("post_nba_node", post_nba_node)
    graph.add_node("sar_explainability_node", sar_explainability_node)
    graph.add_node("update_memory_node", update_memory_node)

    graph.add_edge(START, "trigger_node")
    graph.add_edge("trigger_node", "investigate_node")
    graph.add_edge("investigate_node", "gather_evidence_node")
    graph.add_edge("gather_evidence_node", "assess_risk_node")
    graph.add_edge("assess_risk_node", "pre_nba_node")
    graph.add_edge("pre_nba_node", "extra_evidence_node")
    graph.add_edge("extra_evidence_node", "post_nba_node")
    graph.add_edge("post_nba_node", "sar_explainability_node")
    graph.add_edge("sar_explainability_node", "update_memory_node")
    graph.add_edge("update_memory_node", END)

    return graph.compile()


def run_investigation(trigger: TriggerEvent) -> FraudAgentState:
    """
    Execute full fraud investigation workflow.
    Uses compiled LangGraph StateGraph if available, falling back to sequential execution.
    Returns the completed FraudAgentState dictionary.
    """
    start_time = time.time()
    state = new_case_state(trigger)

    if _LANGGRAPH_AVAILABLE and StateGraph is not None:
        try:
            app = build_workflow()
            if app is not None:
                final_state = app.invoke(state)
                final_state["latency_s"] = round(time.time() - start_time, 2)
                return final_state
        except Exception as e:
            logger.warning(f"LangGraph execution encountered error: {e}. Falling back to sequential execution.")

    # Sequential fallback execution
    state = trigger_node(state)
    state = investigate_node(state)
    state = gather_evidence_node(state)
    state = assess_risk_node(state)
    state = pre_nba_node(state)
    state = extra_evidence_node(state)
    state = post_nba_node(state)
    state = sar_explainability_node(state)
    state = update_memory_node(state)

    state["latency_s"] = round(time.time() - start_time, 2)
    return state


def run_investigation_sequential(trigger: TriggerEvent) -> Dict[str, Any]:
    """Execute the 9 investigation nodes and return formatted competition deliverable result dict."""
    final_state = run_investigation(trigger)
    return state_to_result_dict(final_state)
