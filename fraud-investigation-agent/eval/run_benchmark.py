"""
eval/run_benchmark.py
──────────────────────
Automated evaluation runner for all 20 HHGOA benchmark test cases.

For each case:
  1. Load the benchmark scenario from data/benchmark_cases/
  2. Construct a mock graph state matching the scenario
  3. Run the full agent lifecycle
  4. Save structured result JSON to eval/results/

Usage:
  python eval/run_benchmark.py [--case 001] [--all] [--verbose]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ─── Setup path ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eval")

from agent.state import (
    GraphEvidence,
    TriggerEvent,
    TriggerType,
    state_to_result_dict,
)
from agent.workflow import run_investigation
from graph.tigergraph_client import MockFraudGraph

BENCHMARK_DIR = PROJECT_ROOT / "data" / "benchmark_cases"
RESULTS_DIR   = PROJECT_ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Case Loader
# ============================================================

def load_benchmark_case(case_path: Path) -> Dict[str, Any]:
    """Load a single benchmark case from JSON."""
    with open(case_path) as f:
        return json.load(f)


def patch_mock_graph(scenario: Dict[str, Any]) -> None:
    """
    Inject the benchmark scenario into the MockFraudGraph so that
    graph queries return scenario-specific evidence.
    """
    from graph.tigergraph_client import _mock_instance, MockFraudGraph
    import graph.tigergraph_client as tg_module

    # Create fresh mock and patch it with scenario data
    mock = MockFraudGraph()
    tg_module._mock_instance = mock

    gs = scenario.get("graph_scenario", {})
    acct_id = scenario["initial_trigger"]["account_id"]

    # Override detect_shared_entities to return scenario data
    def _patched_shared(account_id, window_days=30):
        return {
            "shared_device_accounts": gs.get("shared_device_accounts", []),
            "shared_ip_accounts":     gs.get("shared_ip_accounts", []),
            "shared_card_accounts":   [],
        }

    def _patched_velocity(account_id, lookback_hours=72):
        total = gs.get("sub_transactions") and len(gs["sub_transactions"]) or 5
        amount = scenario["initial_trigger"]["amount"]
        burst = gs.get("velocity_burst_score", 2.0)
        return {
            "total_txn_count":      total,
            "total_amount":         amount,
            "avg_txn_amount":       amount / max(total, 1),
            "max_txn_amount":       amount,
            "txn_per_hour":         burst / 3,
            "unique_device_count":  2 if gs.get("new_device_detected") else 1,
            "unique_ip_count":      1 + len(gs.get("shared_ip_accounts", [])),
            "velocity_burst_score": burst,
        }

    def _patched_rings():
        ring_size = gs.get("ring_size", 0)
        members   = [acct_id] + gs.get("shared_device_accounts", [])[:ring_size-1]
        return {
            "components":          [{"component_id": "COMP_0", "members": members, "size": ring_size}] if ring_size >= 3 else [],
            "total_components":    1 if ring_size >= 3 else 0,
            "largest_ring_size":   ring_size,
        }

    def _patched_subgraph(account_id, hop=2):
        nodes = [{"node_id": account_id, "node_type": "Account", "attributes": {"status": "ACTIVE", "risk_score_current": scenario["initial_trigger"]["initial_risk"]}}]
        if gs.get("device_id"):
            nodes.append({"node_id": gs["device_id"], "node_type": "Device",
                          "attributes": {"risk_score": 0.85 if gs.get("new_device_detected") else 0.2,
                                         "is_emulator": False}})
        if gs.get("ip_address"):
            nodes.append({"node_id": gs["ip_address"], "node_type": "IP_Address",
                          "attributes": {"country": gs.get("ip_country", "US"),
                                         "is_proxy": gs.get("ip_proxy", False)}})
        edges = []
        if len(nodes) > 1:
            edges.append({"source": account_id, "target": nodes[1]["node_id"], "edge_type": "USED_DEVICE", "attributes": {}})
        if len(nodes) > 2:
            edges.append({"source": account_id, "target": nodes[2]["node_id"], "edge_type": "USED_IP", "attributes": {}})
        return {"nodes": nodes, "edges": edges}

    # Monkey-patch the mock instance
    import types
    mock.detect_shared_entities = _patched_shared
    mock.trace_velocity         = _patched_velocity
    mock.detect_fraud_rings     = _patched_rings
    mock.get_subgraph           = _patched_subgraph


# ============================================================
# Single Case Runner
# ============================================================

def run_single_case(case_data: Dict[str, Any], verbose: bool = False) -> Dict[str, Any]:
    """Run the fraud agent on a single benchmark case."""
    trigger_data = case_data["initial_trigger"]
    case_id      = case_data["case_id"]

    # Patch mock graph with scenario data
    patch_mock_graph(case_data)

    # Build trigger
    trigger = TriggerEvent(
        case_id        = case_id,
        account_id     = trigger_data["account_id"],
        transaction_id = trigger_data.get("transaction_id"),
        trigger_type   = TriggerType(trigger_data.get("trigger_type", "HIGH_RISK_SCORE")),
        initial_risk   = float(trigger_data["initial_risk"]),
        amount         = float(trigger_data.get("amount", 0.0)),
        timestamp      = trigger_data.get("timestamp", datetime.utcnow().isoformat()),
    )

    t0 = time.time()
    final_state = run_investigation(trigger)
    elapsed_ms  = round((time.time() - t0) * 1000)

    # Serialise to result format
    result = state_to_result_dict(final_state)
    result["_benchmark"] = {
        "case_file":         case_data.get("case_id"),
        "typology":          case_data.get("typology"),
        "elapsed_ms":        elapsed_ms,
        "expected":          case_data.get("expected", {}),
        "run_ts":            datetime.utcnow().isoformat(),
    }

    # Score against expected
    expected = case_data.get("expected", {})
    post_act = result.get("post_evidence_recommendation", {})
    score = {
        "typology_match":  post_act.get("fraud_typology") == expected.get("fraud_typology"),
        "sar_match":       result.get("sar_filing_required") == expected.get("sar_required"),
        "action_match":    post_act.get("action") == expected.get("post_evidence_action"),
    }
    result["_score"] = score
    pass_count = sum(1 for v in score.values() if v)
    result["_pass_rate"] = f"{pass_count}/{len(score)}"

    if verbose:
        print(f"\n  Case {case_id}:")
        print(f"    Typology:  {post_act.get('fraud_typology')} (expected: {expected.get('fraud_typology')}) {'✓' if score['typology_match'] else '✗'}")
        print(f"    Action:    {post_act.get('action')} (expected: {expected.get('post_evidence_action')}) {'✓' if score['action_match'] else '✗'}")
        print(f"    SAR:       {result.get('sar_filing_required')} (expected: {expected.get('sar_required')}) {'✓' if score['sar_match'] else '✗'}")
        print(f"    Score:     {result['_pass_rate']}  [{elapsed_ms}ms]")

    return result


# ============================================================
# Full Benchmark Runner
# ============================================================

def run_all_cases(verbose: bool = False) -> List[Dict[str, Any]]:
    """Run all 20 benchmark cases and save results."""
    case_files = sorted(BENCHMARK_DIR.glob("case_*.json"))

    if not case_files:
        logger.warning(f"No benchmark cases found in {BENCHMARK_DIR}")
        logger.info("Generating benchmark cases first...")
        from data.generate_benchmark import generate_all_cases
        generate_all_cases()
        case_files = sorted(BENCHMARK_DIR.glob("case_*.json"))

    results      = []
    pass_counts  = []
    total_score  = 0

    print(f"\n{'='*60}")
    print(f"  HHGOA Fraud Agent — Benchmark Evaluation")
    print(f"  Cases: {len(case_files)} | Mode: {'VERBOSE' if verbose else 'SUMMARY'}")
    print(f"{'='*60}")

    for i, case_file in enumerate(case_files, 1):
        case_data = load_benchmark_case(case_file)
        case_id   = case_data.get("case_id", case_file.stem)
        typology  = case_data.get("typology", "?")

        if not verbose:
            print(f"  [{i:02d}/20] Running {case_id} [{typology}]...", end=" ", flush=True)

        try:
            result = run_single_case(case_data, verbose=verbose)
            results.append(result)

            # Save result file
            result_path = RESULTS_DIR / f"{case_id}_result.json"
            with open(result_path, "w") as f:
                json.dump(result, f, indent=2, default=str)

            score_str = result.get("_pass_rate", "0/3")
            passes    = int(score_str.split("/")[0])
            pass_counts.append(passes)
            total_score += passes

            if not verbose:
                print(f"✓ {score_str} [{result['_benchmark'].get('elapsed_ms', 0)}ms]")

        except Exception as e:
            logger.error(f"Case {case_id} FAILED: {e}", exc_info=True)
            if not verbose:
                print(f"✗ ERROR: {e}")
            pass_counts.append(0)

    # Summary
    total_possible = len(case_files) * 3  # 3 metrics per case
    overall_pct    = (total_score / max(total_possible, 1)) * 100

    print(f"\n{'='*60}")
    print(f"  BENCHMARK RESULTS")
    print(f"  Cases Evaluated:  {len(results)}/20")
    print(f"  Overall Score:    {total_score}/{total_possible} ({overall_pct:.1f}%)")
    print(f"  Results saved to: {RESULTS_DIR}")
    print(f"{'='*60}\n")

    # Save summary
    summary = {
        "run_ts":          datetime.utcnow().isoformat(),
        "total_cases":     len(case_files),
        "completed":       len(results),
        "total_score":     total_score,
        "total_possible":  total_possible,
        "overall_pct":     round(overall_pct, 2),
        "case_pass_rates": [r.get("_pass_rate") for r in results],
    }
    with open(RESULTS_DIR / "benchmark_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return results


# ============================================================
# CLI
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="HHGOA Fraud Agent Benchmark Evaluator")
    parser.add_argument("--case",    type=str, help="Run a single case by number (e.g. 001)")
    parser.add_argument("--all",     action="store_true", default=True, help="Run all 20 cases")
    parser.add_argument("--verbose", action="store_true", help="Verbose output per case")
    args = parser.parse_args()

    if args.case:
        case_file = BENCHMARK_DIR / f"case_{args.case.zfill(3)}.json"
        if not case_file.exists():
            print(f"Case file not found: {case_file}")
            sys.exit(1)
        case_data = load_benchmark_case(case_file)
        result    = run_single_case(case_data, verbose=True)
        print(json.dumps(result, indent=2, default=str))
    else:
        run_all_cases(verbose=args.verbose)


if __name__ == "__main__":
    main()
