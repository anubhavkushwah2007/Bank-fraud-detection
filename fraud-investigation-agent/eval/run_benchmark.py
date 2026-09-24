"""
eval/run_benchmark.py
──────────────────────
Official benchmark runner for all 20 Hacker House Goa exam cases from case_pack.csv.

Enforces:
1. Decision logic blindness: fails if 'HHG-' is found in any file under agent/ or graph/.
2. Authentic case loading: loads case_pack.csv with authentic customer_id != card_id.
3. Strict mode: checks live TigerGraph connectivity and refuses to run if unreachable.
4. Output format compliance: writes cases/<case_id>.json matching DATASET_README.md.
5. Real metrics: tracks real tool calls, real LLM tokens (summed over case), and wall-clock latency.
6. Summary reporting: prints formatted summary table at end of run.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure UTF-8 encoding for Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmark")

import pandas as pd

from agent.llm_client import get_rate_limited_llm
from agent.state import (
    PolicyAction,
    TriggerEvent,
    TriggerType,
)
from agent.workflow import run_investigation_sequential
from config import settings
from graph.tigergraph_client import get_graph_client, set_graph_client, TigerGraphClient

CASE_PACK_CSV = settings.CASE_PACK_CSV
CASES_DIR     = settings.CASES_OUTPUT_DIR
CASES_DIR.mkdir(parents=True, exist_ok=True)


def check_no_case_id_leak() -> None:
    """
    Ensure decision logic is blind to case IDs:
    Fail if the string 'HHG-' appears in any code file under agent/ or graph/.
    """
    forbidden = "HHG-"
    leaks = []
    for search_dir in [PROJECT_ROOT / "agent", PROJECT_ROOT / "graph"]:
        if not search_dir.exists():
            continue
        for py_file in search_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                if forbidden in content:
                    leaks.append(f"{py_file.relative_to(PROJECT_ROOT)} contains '{forbidden}'")
            except Exception as e:
                logger.warning(f"Could not read {py_file}: {e}")

    if leaks:
        print("\n" + "!" * 75)
        print("VIOLATION: Case ID leak detected! The agent must not read case IDs in decision logic.")
        for leak in leaks:
            print(f"  - {leak}")
        print("!" * 75 + "\n")
        raise RuntimeError("Benchmark aborted due to case ID leak in agent/ or graph/.")


def load_all_cases() -> List[Dict[str, Any]]:
    """
    Load cases from case_pack.csv only:
    (case_id, opened_at, trigger_type, trigger_text, flagged_txn_id, card_id, customer_id, risk_score).
    Use real customer_id from the file. Do not set customer_id = card_id.
    """
    if not CASE_PACK_CSV.exists():
        raise FileNotFoundError(f"case_pack.csv not found at {CASE_PACK_CSV}")

    df = pd.read_csv(CASE_PACK_CSV)
    required_cols = [
        "case_id", "opened_at", "trigger_type", "trigger_text",
        "flagged_txn_id", "card_id", "customer_id", "risk_score"
    ]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Missing required column '{col}' in {CASE_PACK_CSV}")

    cases = []
    for _, row in df.iterrows():
        raw_score = row.get("risk_score")
        score = float(raw_score) if pd.notna(raw_score) and str(raw_score).strip() else None

        cases.append({
            "case_id":        str(row["case_id"]).strip(),
            "opened_at":      str(row["opened_at"]).strip(),
            "trigger_type":   str(row["trigger_type"]).strip(),
            "trigger_text":   str(row.get("trigger_text", "")).strip(),
            "flagged_txn_id": str(int(row["flagged_txn_id"])).strip(),
            "card_id":        str(row["card_id"]).strip(),
            "customer_id":    str(row["customer_id"]).strip(),
            "risk_score":     score,
        })
    return cases


def verify_strict_connection() -> None:
    """Refuse to start if OFFLINE_DEV is true or the graph is unreachable."""
    if settings.OFFLINE_DEV:
        msg = "STRICT ERROR: OFFLINE_DEV is true. Strict benchmark run requires live TigerGraph connection."
        logger.error(msg)
        raise RuntimeError(msg)

    client = get_graph_client()
    if not client or not client.conn:
        msg = "STRICT ERROR: TigerGraph is unreachable or connection is not established."
        logger.error(msg)
        raise RuntimeError(msg)

    try:
        ver = client.conn.getVer()
        logger.info(f"Verified live TigerGraph connection: {ver}")
    except Exception as e:
        msg = f"STRICT ERROR: TigerGraph liveness check failed: {e}"
        logger.error(msg)
        raise RuntimeError(msg)


def run_single_case(case_info: Dict[str, Any]) -> Dict[str, Any]:
    """Execute investigation on a single benchmark case and save result."""
    cid = case_info["case_id"]
    logger.info(f"▶ Starting investigation for {cid} ({case_info['trigger_type']}) on card {case_info['card_id']}")

    tt_str = case_info["trigger_type"]
    try:
        tt_enum = TriggerType(tt_str)
    except ValueError:
        logger.warning(f"Unknown trigger type '{tt_str}', defaulting to RISK_SCORE")
        tt_enum = TriggerType.RISK_SCORE

    trigger = TriggerEvent(
        case_id=cid,
        card_id=case_info["card_id"],
        customer_id=case_info["customer_id"],
        trigger_type=tt_enum,
        flagged_txn_id=case_info["flagged_txn_id"],
        risk_score=case_info["risk_score"],
        opened_at=case_info["opened_at"],
        trigger_text=case_info["trigger_text"],
    )

    t0 = time.time()
    result = run_investigation_sequential(trigger)
    elapsed = time.time() - t0
    result["latency_s"] = round(elapsed, 2)

    # Save to cases/<case_id>.json
    out_file = CASES_DIR / f"{cid}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Also sync to root cases/ if present
    parent_cases = PROJECT_ROOT.parent / "cases"
    if parent_cases.exists() and parent_cases.resolve() != CASES_DIR.resolve():
        parent_out = parent_cases / f"{cid}.json"
        with open(parent_out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

    return result


def print_summary_table(results: List[Dict[str, Any]]) -> None:
    """Print clean summary table of all benchmark cases."""
    print("\n" + "=" * 120)
    print("  HHGOA FRAUD INVESTIGATION BENCHMARK — SUMMARY RESULTS")
    print("=" * 120)
    header = (
        f"{'Case ID':<10} | {'Verdict':<11} | {'Prob':<6} | {'Pattern':<28} | "
        f"{'Final Actions':<26} | {'SAR':<5} | {'Tokens':<7} | {'Latency':<8} | {'Graph'}"
    )
    print(header)
    print("-" * 120)

    for r in results:
        cid = r.get("case_id", "")
        c = r.get("case", {})
        verdict = c.get("verdict", "")
        prob = f"{c.get('fraud_probability', 0.0):.2f}"
        pattern = c.get("pattern", "")[:28]
        actions_list = [a.get("action", "") for a in r.get("next_best_actions", {}).get("final", [])]
        actions_str = ", ".join(actions_list)[:26]
        sar_str = "YES" if r.get("sar", {}).get("file", False) else "NO"
        tokens = str(r.get("tokens", 0))
        latency = f"{r.get('latency_s', 0.0):.2f}s"
        graph_ok = "YES" if c.get("written_to_graph", False) else "NO"

        print(
            f"{cid:<10} | {verdict:<11} | {prob:<6} | {pattern:<28} | "
            f"{actions_str:<26} | {sar_str:<5} | {tokens:<7} | {latency:<8} | {graph_ok}"
        )

    print("=" * 120 + "\n")


def sanity_check_distribution(results: List[Dict[str, Any]]) -> None:
    """
    Sanity pass on the generated answer files:
    'Half the cases are legitimate... An agent that blocks everything scores badly.'
    Warns if BLOCK_CARD or FILE_REPORT is over-recommended (>12 of 20).
    """
    total = len(results)
    if total == 0:
        return

    verdicts: Dict[str, int] = {}
    patterns: Dict[str, int] = {}
    block_count = 0
    sar_count = 0
    legit_count = 0

    for r in results:
        v = r["case"]["verdict"]
        p = r["case"]["pattern"]
        verdicts[v] = verdicts.get(v, 0) + 1
        patterns[p] = patterns.get(p, 0) + 1

        actions = [a["action"] for a in r["next_best_actions"]["final"]]
        if any("BLOCK" in a for a in actions):
            block_count += 1
        if r["sar"]["file"] or any(a == PolicyAction.FILE_REPORT.value for a in actions):
            sar_count += 1
        if v == "legitimate":
            legit_count += 1

    print("-" * 65)
    print("DISTRIBUTION SANITY PASS (Anti-Overflagging Check):")
    print("-" * 65)
    print(f"Total Cases Evaluated:       {total}")
    print(f"Verdicts:                    {verdicts}")
    print(f"Patterns:                    {patterns}")
    print(f"Cases with Legitimate:       {legit_count} ({legit_count/total:.0%})")
    print(f"Cases Recommending BLOCK:    {block_count} ({block_count/total:.0%})")
    print(f"Cases Recommending SAR File: {sar_count} ({sar_count/total:.0%})")
    print("-" * 65)

    if block_count > 12:
        logger.warning(
            f"⚠️ SANITY WARNING: {block_count}/{total} cases recommended BLOCK. "
            "Competition specification warns: 'Half the cases are legitimate... An agent that blocks everything scores badly.'"
        )
    else:
        print(f"✅ SANITY CHECK PASSED: Balanced distribution ({legit_count} legitimate, {total - legit_count} fraud/uncertain).")
    print("-" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="HHGOA Fraud Investigation Benchmark Runner")
    parser.add_argument("--case", type=str, default=None, help="Run specific case, e.g. HHG-014")
    parser.add_argument("--all", action="store_true", default=False, help="Run all 20 cases")
    parser.add_argument("--strict", action="store_true", default=False, help="Refuse to start if OFFLINE_DEV is true or TigerGraph is unreachable")
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="Enable verbose debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)

    # 1. Check for case ID leaks in agent/ or graph/
    check_no_case_id_leak()

    # 2. Strict connectivity check if requested
    if args.strict:
        verify_strict_connection()
    else:
        if not settings.OFFLINE_DEV:
            try:
                client = get_graph_client()
                if client and client.conn:
                    client.conn.getVer()
            except Exception as e:
                logger.warning(f"TigerGraph Cloud is unreachable ({e}). Setting OFFLINE_DEV=True to use authentic local parquet dataset.")
                settings.OFFLINE_DEV = True
                set_graph_client(TigerGraphClient())

    # 3. Load cases from case_pack.csv only
    all_cases = load_all_cases()
    logger.info(f"Loaded {len(all_cases)} cases from {CASE_PACK_CSV}")

    # 4. Handle single-case execution
    if args.case:
        target = [c for c in all_cases if c["case_id"] == args.case]
        if not target:
            logger.error(f"Case {args.case} not found in {CASE_PACK_CSV}!")
            sys.exit(1)
        res = run_single_case(target[0])
        print_summary_table([res])
        return

    # 5. Handle all cases
    results = []
    print("\n" + "═" * 65)
    print("  HHGOA FRAUD INVESTIGATION BENCHMARK — RUNNING 20 CASES")
    print("═" * 65 + "\n")

    for i, c in enumerate(all_cases, 1):
        cid = c["case_id"]
        out_file = CASES_DIR / f"{cid}.json"
        if out_file.exists():
            try:
                with open(out_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("case", {}).get("written_to_graph") and not existing.get("offline_dev"):
                    print(f"[{i:02d}/20] Case {cid} already completed live on TigerGraph. (Skipping)")
                    results.append(existing)
                    continue
            except Exception:
                pass

        print(f"[{i:02d}/20] Processing {cid}...")
        res = run_single_case(c)
        results.append(res)

    print_summary_table(results)
    sanity_check_distribution(results)
    print(f"All 20 answer files saved to {CASES_DIR}/")


if __name__ == "__main__":
    main()
