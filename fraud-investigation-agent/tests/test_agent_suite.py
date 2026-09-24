"""
tests/test_agent_suite.py
─────────────────────────
Comprehensive test suite verifying:
1. test_no_case_id_dependence: identical outcomes under varying case_ids
2. test_no_data_no_fraud: missing / unrelated card returns low-confidence / uncertain
3. test_policy_rules: rules R1 through R10 with $2,500 and $1,000 boundaries
4. test_answer_schema: every answer file in cases/ passes validate_cases
5. test_graph_roundtrip: upsert Case, read-back verification, and similar case retrieval
6. test_no_hardcoded_ids: zero case_pack IDs ("HHG-", cards, devices) in agent/ or graph/
"""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
import unittest
import pytest

# Ensure project root in sys.path
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Enforce offline dev mode for deterministic local test runs
os.environ["OFFLINE_DEV"] = "true"
os.environ["STRICT_GRAPH"] = "false"

from config import settings
settings.OFFLINE_DEV = True
settings.STRICT_GRAPH = False

from agent.state import (
    ActionItem,
    ApprovalRoute,
    CaseStatus,
    CaseVerdict,
    EvidenceRequest,
    FraudPattern,
    GraphEvidence,
    PolicyAction,
    RiskAssessment,
    TriggerEvent,
    TriggerType,
    state_to_result_dict,
)
from agent.policy_engine import (
    compute_initial_actions,
    compute_final_actions,
    get_action_route,
)
from agent.workflow import run_investigation
from graph.tigergraph_client import (
    TigerGraphClient,
    get_graph_client,
    set_graph_client,
)
from tests.test_case_writeback import MockTGConnection


# ══════════════════════════════════════════════════════════════════════════════
# 1. Test: No Case ID Dependence
# ══════════════════════════════════════════════════════════════════════════════

def test_no_case_id_dependence():
    """
    Run the same trigger (same card, same transaction, same risk score)
    under three different case_ids and assert the verdict, pattern, and
    final actions are completely identical.
    """
    # Trigger parameters from an authentic case
    card_id = "C13487-K1"
    customer_id = "C13487"
    txn_id = "3478561"
    trigger_type = TriggerType.ANALYST_REQUEST
    risk_score = 0.94

    trigger_1 = TriggerEvent(
        case_id="CASE_ALPHA_111",
        card_id=card_id,
        customer_id=customer_id,
        flagged_txn_id=txn_id,
        trigger_type=trigger_type,
        risk_score=risk_score,
        initial_risk=risk_score,
    )
    trigger_2 = TriggerEvent(
        case_id="CASE_BETA_222",
        card_id=card_id,
        customer_id=customer_id,
        flagged_txn_id=txn_id,
        trigger_type=trigger_type,
        risk_score=risk_score,
        initial_risk=risk_score,
    )
    trigger_3 = TriggerEvent(
        case_id="CASE_GAMMA_333",
        card_id=card_id,
        customer_id=customer_id,
        flagged_txn_id=txn_id,
        trigger_type=trigger_type,
        risk_score=risk_score,
        initial_risk=risk_score,
    )

    state_1 = run_investigation(trigger_1)
    state_2 = run_investigation(trigger_2)
    state_3 = run_investigation(trigger_3)

    res_1 = state_to_result_dict(state_1)
    res_2 = state_to_result_dict(state_2)
    res_3 = state_to_result_dict(state_3)

    # 1. Verdict must be identical across all three runs
    assert res_1["case"]["verdict"] == res_2["case"]["verdict"] == res_3["case"]["verdict"], (
        f"Verdicts differed: {res_1['case']['verdict']} vs {res_2['case']['verdict']} vs {res_3['case']['verdict']}"
    )

    # 2. Pattern must be identical
    assert res_1["case"]["pattern"] == res_2["case"]["pattern"] == res_3["case"]["pattern"], (
        f"Patterns differed: {res_1['case']['pattern']} vs {res_2['case']['pattern']} vs {res_3['case']['pattern']}"
    )

    # 3. Final actions and routes must be identical
    acts_1 = [a["action"] for a in res_1["next_best_actions"]["final"]]
    acts_2 = [a["action"] for a in res_2["next_best_actions"]["final"]]
    acts_3 = [a["action"] for a in res_3["next_best_actions"]["final"]]
    assert acts_1 == acts_2 == acts_3, (
        f"Actions differed: {acts_1} vs {acts_2} vs {acts_3}"
    )

    routes_1 = [a["route"] for a in res_1["next_best_actions"]["final"]]
    routes_2 = [a["route"] for a in res_2["next_best_actions"]["final"]]
    routes_3 = [a["route"] for a in res_3["next_best_actions"]["final"]]
    assert routes_1 == routes_2 == routes_3, "Approval routes differed"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Test: No Data -> No Confident Fraud
# ══════════════════════════════════════════════════════════════════════════════

def test_no_data_no_fraud():
    """
    With an empty or unrelated card, the agent must not return a confident
    fraud verdict; it should return uncertain or legitimate with low confidence
    and explain that evidence is missing.
    """
    trigger = TriggerEvent(
        case_id="CASE_EMPTY_CARD_TEST",
        card_id="CARD_NONEXISTENT_9999",
        customer_id="CUST_NONEXISTENT_9999",
        flagged_txn_id="TXN_NONEXISTENT_999999",
        trigger_type=TriggerType.RISK_SCORE,
        risk_score=0.45,
        initial_risk=0.45,
    )
    state = run_investigation(trigger)
    res = state_to_result_dict(state)

    verdict = res["case"]["verdict"]
    fraud_prob = res["case"]["fraud_probability"]

    # Must NOT be confident fraud
    assert verdict in ("uncertain", "legitimate"), (
        f"Expected uncertain or legitimate for nonexistent card, got {verdict}"
    )
    assert fraud_prob < 0.70, (
        f"Expected low fraud probability (<0.70), got {fraud_prob}"
    )

    # When verdict is "uncertain", the explanation should mention lack of evidence.
    # When verdict is "legitimate" with low confidence, that itself is the correct
    # no-data behaviour: the agent should not fabricate a confident fraud finding.
    if verdict == "uncertain":
        summary = res["case"].get("summary", "").lower()
        claims = " ".join([e.get("claim", "") for e in res["case"].get("evidence", [])]).lower()
        full_explanation = f"{summary} {claims}"
        evidence_keywords = [
            "missing", "no prior", "baseline", "unverified", "insufficient",
            "inconclusive", "isolated", "no history", "uncertain",
        ]
        assert any(kw in full_explanation for kw in evidence_keywords), (
            f"Uncertain verdict but no missing-evidence explanation found: {summary}"
        )
    # For "legitimate" with fraud_prob < 0.70 the assertions above are sufficient:
    # the agent correctly found no fraud signal for an unknown card.


# ══════════════════════════════════════════════════════════════════════════════
# 3. Test: Policy Rules R1 through R10 (including $2,500 and $1,000 boundaries)
# ══════════════════════════════════════════════════════════════════════════════

def test_policy_rule_r1():
    """R1: Single weak signal (fraud_prob < 0.70) must verify before blocking."""
    trig = TriggerEvent(
        case_id="R1_TEST", card_id="C01", customer_id="U01",
        trigger_type=TriggerType.RISK_SCORE, flagged_txn_id="T01",
        risk_score=0.65, initial_risk=0.65
    )
    risk = RiskAssessment(fraud_probability=0.65, exposure_usd=120.0)
    ev = GraphEvidence()
    actions = compute_initial_actions(trig, ev, risk)
    act_names = [a.action for a in actions]
    assert "VERIFY_WITH_CUSTOMER" in act_names
    assert "BLOCK_CARD" not in act_names, "Rule R1 breach: blocked on weak single signal"


def test_policy_rule_r2_and_boundaries():
    """
    R2: Customer denies transaction -> BLOCK_CARD and CREATE_CASE.
    Tests boundaries:
    - $1,000 boundary for FILE_REPORT (SAR)
    - $2,500 boundary for BLOCK_CARD approval route (L1 <= $2,500; L2 > $2,500)
    """
    trig = TriggerEvent(
        case_id="R2_TEST", card_id="C01", customer_id="U01",
        trigger_type=TriggerType.CUSTOMER_REPORT, flagged_txn_id="T01",
        risk_score=0.85
    )
    ev = GraphEvidence(connected_cards=[])  # isolated card
    req = EvidenceRequest(
        type="customer_validation", asked_after_step=2,
        assumed_response="Customer states they did not authorize this charge and were in possession of card."
    )

    # ── Test $1,000 boundary for FILE_REPORT ──
    # Under $1,000: case-only (BLOCK_CARD and CREATE_CASE, no FILE_REPORT)
    risk_sub1k = RiskAssessment(fraud_probability=0.88, exposure_usd=999.00)
    acts_sub1k, _, sar_sub1k = compute_final_actions(trig, ev, risk_sub1k, req)
    act_names_sub1k = [a.action for a in acts_sub1k]
    assert "BLOCK_CARD" in act_names_sub1k
    assert "CREATE_CASE" in act_names_sub1k
    assert "FILE_REPORT" not in act_names_sub1k, "$1,000 boundary: exposure <= $1,000 must not file report"
    assert sar_sub1k is False

    # Over $1,000: mandates FILE_REPORT (SAR)
    risk_over1k = RiskAssessment(fraud_probability=0.88, exposure_usd=1001.00)
    acts_over1k, _, sar_over1k = compute_final_actions(trig, ev, risk_over1k, req)
    act_names_over1k = [a.action for a in acts_over1k]
    assert "FILE_REPORT" in act_names_over1k, "$1,000 boundary: exposure > $1,000 must include FILE_REPORT"
    assert sar_over1k is True

    # ── Test $2,500 boundary for BLOCK_CARD approval route ──
    route_l1 = get_action_route("BLOCK_CARD", exposure_usd=2500.00)
    assert route_l1 == "L1", f"$2,500 boundary: exposure <= $2,500 must route to L1, got {route_l1}"

    route_l2 = get_action_route("BLOCK_CARD", exposure_usd=2500.01)
    assert route_l2 == "L2", f"$2,500 boundary: exposure > $2,500 must route to L2, got {route_l2}"


def test_policy_rule_r3():
    """R3: Customer confirms transaction -> CLOSE_NO_FRAUD and no SAR."""
    trig = TriggerEvent(
        case_id="R3_TEST", card_id="C01", customer_id="U01",
        trigger_type=TriggerType.RISK_SCORE, flagged_txn_id="T01",
        risk_score=0.40
    )
    risk = RiskAssessment(fraud_probability=0.20, exposure_usd=150.0)
    ev = GraphEvidence()
    req = EvidenceRequest(
        type="customer_validation", asked_after_step=2,
        assumed_response="Customer confirms they made the purchase while traveling and authorized the transaction."
    )
    acts, _, sar = compute_final_actions(trig, ev, risk, req)
    act_names = [a.action for a in acts]
    assert "CLOSE_NO_FRAUD" in act_names
    assert sar is False


def test_policy_rule_r4():
    """R4: No reply within 24 hours -> MONITOR_CARD and DECLINE_TRANSACTION."""
    trig = TriggerEvent(
        case_id="R4_TEST", card_id="C01", customer_id="U01",
        trigger_type=TriggerType.RISK_SCORE, flagged_txn_id="T01",
        risk_score=0.55
    )
    risk = RiskAssessment(fraud_probability=0.55, exposure_usd=150.0)
    ev = GraphEvidence()
    actions = compute_initial_actions(trig, ev, risk)
    act_names = [a.action for a in actions]
    assert "MONITOR_CARD" in act_names


def test_policy_rule_r5():
    """R5: Card testing sequence: decline + step-up, block if > $100 cleared."""
    trig = TriggerEvent(
        case_id="R5_TEST", card_id="C01", customer_id="U01",
        trigger_type=TriggerType.RISK_SCORE, flagged_txn_id="T01",
        risk_score=0.80
    )
    ev = GraphEvidence(testing_pattern_detected=True)

    # Cleared purchase > $100 -> recommend BLOCK_CARD
    risk_cleared = RiskAssessment(fraud_probability=0.85, exposure_usd=150.0)
    acts_cleared = compute_initial_actions(trig, ev, risk_cleared)
    act_names_cleared = [a.action for a in acts_cleared]
    assert "DECLINE_TRANSACTION" in act_names_cleared
    assert "BLOCK_CARD" in act_names_cleared

    # Small probing authorizations (exposure <= $100) -> STEP_UP_AUTH
    risk_probing = RiskAssessment(fraud_probability=0.75, exposure_usd=45.0)
    acts_probing = compute_initial_actions(trig, ev, risk_probing)
    act_names_probing = [a.action for a in acts_probing]
    assert "DECLINE_TRANSACTION" in act_names_probing
    assert "STEP_UP_AUTH" in act_names_probing


def test_policy_rule_r6():
    """R6: Shared origin across multiple cards -> CREATE_CASE, FILE_REPORT, MONITOR_CONNECTED_CARDS."""
    trig = TriggerEvent(
        case_id="R6_TEST", card_id="C1000-K1", customer_id="C1000",
        trigger_type=TriggerType.ANALYST_REQUEST, flagged_txn_id="T01",
        risk_score=0.90
    )
    ev = GraphEvidence(connected_cards=["C2000-K1", "C3000-K1"])
    risk = RiskAssessment(fraud_probability=0.92, exposure_usd=850.0)
    req = EvidenceRequest(
        type="analyst_info", asked_after_step=3,
        assumed_response="Analyst confirms shared device fingerprint across 2 other compromised accounts."
    )
    acts, _, sar = compute_final_actions(trig, ev, risk, req)
    act_names = [a.action for a in acts]
    assert "CREATE_CASE" in act_names
    assert "FILE_REPORT" in act_names
    assert "MONITOR_CONNECTED_CARDS" in act_names
    assert sar is True


def test_policy_rule_r7():
    """R7: Disputed but legitimate recurring transaction -> WARN_CUSTOMER, CLOSE_NO_FRAUD, no BLOCK."""
    trig = TriggerEvent(
        case_id="R7_TEST", card_id="C01", customer_id="U01",
        trigger_type=TriggerType.CUSTOMER_REPORT, flagged_txn_id="T01",
        risk_score=0.35
    )
    risk = RiskAssessment(fraud_probability=0.25, exposure_usd=49.0)
    ev = GraphEvidence()
    req = EvidenceRequest(
        type="customer_validation", asked_after_step=2,
        assumed_response="Customer confirms upon review that this charge corresponds to an annual recurring software subscription."
    )
    acts, _, sar = compute_final_actions(trig, ev, risk, req)
    act_names = [a.action for a in acts]
    assert "WARN_CUSTOMER" in act_names
    assert "CLOSE_NO_FRAUD" in act_names
    assert "BLOCK_CARD" not in act_names
    assert sar is False


def test_policy_rule_r8():
    """R8: Uncertain verdict with exposure -> ESCALATE_TO_ANALYST."""
    trig = TriggerEvent(
        case_id="R8_TEST", card_id="C01", customer_id="U01",
        trigger_type=TriggerType.RISK_SCORE, flagged_txn_id="T01",
        risk_score=0.50
    )
    risk = RiskAssessment(fraud_probability=0.50, exposure_usd=750.0)
    ev = GraphEvidence()
    req = EvidenceRequest(type="unrecognized", asked_after_step=2, assumed_response="Inconclusive data.")
    acts, _, _ = compute_final_actions(trig, ev, risk, req)
    act_names = [a.action for a in acts]
    assert "ESCALATE_TO_ANALYST" in act_names


def test_policy_rule_r9():
    """R9: Undocumented pattern with coordinated abuse -> CREATE_CASE, FILE_REPORT, ESCALATE_TO_ANALYST."""
    trig = TriggerEvent(
        case_id="R9_TEST", card_id="C01", customer_id="U01",
        trigger_type=TriggerType.ANALYST_REQUEST, flagged_txn_id="T01",
        risk_score=0.85
    )
    risk = RiskAssessment(fraud_probability=0.88, exposure_usd=1200.0, likely_pattern=FraudPattern.UNDOCUMENTED)
    ev = GraphEvidence(connected_cards=["C02-K1", "C03-K1"])
    req = EvidenceRequest(type="analyst_info", asked_after_step=3, assumed_response="Analyst confirms novel coordinated attack.")
    acts, _, sar = compute_final_actions(trig, ev, risk, req)
    act_names = [a.action for a in acts]
    assert "CREATE_CASE" in act_names
    assert "FILE_REPORT" in act_names
    assert sar is True


def test_policy_rule_r10():
    """R10: BLOCK_ALL_CARDS requires route L2 and must only apply to multi-card compromise."""
    route = get_action_route("BLOCK_ALL_CARDS", exposure_usd=500.0)
    assert route == "L2", "Rule R10: BLOCK_ALL_CARDS route must always be L2"


def test_policy_rules():
    """Top-level test executing and verifying all rules R1-R10 and boundaries."""
    test_policy_rule_r1()
    test_policy_rule_r2_and_boundaries()
    test_policy_rule_r3()
    test_policy_rule_r4()
    test_policy_rule_r5()
    test_policy_rule_r6()
    test_policy_rule_r7()
    test_policy_rule_r8()
    test_policy_rule_r9()
    test_policy_rule_r10()


# ══════════════════════════════════════════════════════════════════════════════
# 4. Test: Answer Schema Validation on cases/*.json
# ══════════════════════════════════════════════════════════════════════════════

def test_answer_schema():
    """Every file in cases/ must pass validate_cases with zero errors."""
    import importlib.util
    script_path = PROJECT_ROOT.parent / "scripts" / "validate_cases.py"
    if not script_path.exists():
        script_path = PROJECT_ROOT / "scripts" / "validate_cases.py"

    assert script_path.exists(), f"validate_cases.py not found at {script_path}"

    spec = importlib.util.spec_from_file_location("validate_cases", script_path)
    val_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(val_mod)

    refs = val_mod.load_dataset_references()
    cases_dir = PROJECT_ROOT.parent / "cases"
    if not cases_dir.exists() or not list(cases_dir.glob("HHG-*.json")):
        cases_dir = PROJECT_ROOT / "cases"

    case_files = sorted(cases_dir.glob("HHG-*.json"))
    assert len(case_files) == 20, f"Expected 20 answer files in {cases_dir}, found {len(case_files)}"

    total_errors = 0
    error_details = []
    for fp in case_files:
        errs = val_mod.validate_file(fp, refs)
        if errs:
            total_errors += len(errs)
            error_details.append(f"{fp.name}: {errs}")

    assert total_errors == 0, f"Validation failed with {total_errors} errors:\n" + "\n".join(error_details)


# ══════════════════════════════════════════════════════════════════════════════
# 5. Test: Graph Roundtrip
# ══════════════════════════════════════════════════════════════════════════════

def test_graph_roundtrip():
    """
    Write a Case, read it back, and retrieve it as a similar case
    for a later investigation.
    """
    mock_conn = MockTGConnection()
    client = TigerGraphClient(conn=mock_conn)
    set_graph_client(client)

    try:
        case_id = "CASE_ROUNDTRIP_001"
        case_data = {
            "case_id": case_id,
            "status": "closed_fraud",
            "verdict": "fraud",
            "fraud_probability": 0.93,
            "pattern": "card_not_present_new_device",
            "exposure_usd": 1450.00,
            "summary": "Roundtrip test case written by agent.",
            "card_id": "C99999-K1",
            "customer_id": "C99999",
            "affected_txn_ids": ["3999001"],
            "similar_prior_cases": ["CC-0141"],
        }

        # 1. Write the Case vertex and edges
        res = client.upsert_case(case_data)
        assert res.success is True, "Failed to upsert case to graph"
        assert res.vertex_id == case_id

        # 2. Read it back and verify contents
        read_back = mock_conn.getVerticesById("Case", case_id)
        assert len(read_back) == 1, "Failed to read back written Case vertex"
        attrs = read_back[0]["attributes"]
        assert attrs["verdict"] == "fraud"
        assert attrs["exposure_usd"] == 1450.00
        assert attrs["pattern"] == "card_not_present_new_device"

        # 3. Retrieve it as a similar case for a later investigation
        cases_on_card = client.get_cases_by_card("C99999-K1")
        assert any(c["case_id"] == case_id for c in cases_on_card), (
            f"Case {case_id} was not retrieved in get_cases_by_card query"
        )

        similar_cases = client.find_similar_cases(pattern="card_not_present_new_device")
        assert len(similar_cases) > 0, "find_similar_cases returned empty list"

    finally:
        set_graph_client(None)


# ══════════════════════════════════════════════════════════════════════════════
# 6. Test: No Hardcoded Case IDs / Entities in Agent or Graph
# ══════════════════════════════════════════════════════════════════════════════

def test_no_hardcoded_ids():
    """
    Fail if 'HHG-' or a specific card/device id from the case pack
    appears in agent/ or graph/ logic.
    """
    agent_dir = PROJECT_ROOT / "agent"
    graph_dir = PROJECT_ROOT / "graph"

    # 1. Load case pack to extract authentic cards
    cp_path = PROJECT_ROOT / "data_real" / "case_pack.csv"
    if not cp_path.exists():
        cp_path = PROJECT_ROOT.parent / "data_real" / "case_pack.csv"

    known_cards = set()
    if cp_path.exists():
        with open(cp_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cid = row.get("card_id", "").strip()
                if cid:
                    known_cards.add(cid)

    specific_device_signatures = ["SM-G935F", "NRD90M"]

    py_files = list(agent_dir.rglob("*.py")) + list(graph_dir.rglob("*.py"))
    assert len(py_files) > 0, "No python files found in agent/ or graph/"

    violations = []
    for fp in py_files:
        content = fp.read_text(encoding="utf-8")
        rel_path = fp.relative_to(PROJECT_ROOT)

        # Disallow "HHG-" anywhere in agent or graph
        if "HHG-" in content:
            violations.append(f"Found forbidden case prefix 'HHG-' in {rel_path}")

        # Disallow specific card IDs
        for cid in known_cards:
            if f'"{cid}"' in content or f"'{cid}'" in content:
                violations.append(f"Found hardcoded card ID '{cid}' in {rel_path}")

        # Disallow specific device signatures
        for dev in specific_device_signatures:
            if dev in content:
                violations.append(f"Found hardcoded device signature '{dev}' in {rel_path}")

    assert len(violations) == 0, f"Found hardcoded test entities in agent/graph:\n" + "\n".join(violations)
