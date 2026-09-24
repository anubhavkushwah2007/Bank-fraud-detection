"""
eval/run_benchmark.py
──────────────────────
Official benchmark runner for all 20 Hacker House Goa exam cases from data/case_pack.csv.

For each case:
  1. Load case details from data/case_pack.csv (TriggerType: risk_score, customer_report, analyst_request)
  2. Execute the full fraud investigation lifecycle via LangGraph/sequential pipeline
  3. Save answer file to cases/<case_id>.json (with authentic dataset IDs & 15 case fields)
  4. Log execution metrics and remaining Groq rate-limit quota
  5. Run anti-overflagging distribution sanity check across all 20 cases

Usage:
  python eval/run_benchmark.py [--case HHG-001] [--all]
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

# ─── Ensure UTF-8 encoding for Windows consoles ───────────────────────────────
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

CASE_PACK_CSV = PROJECT_ROOT / "data" / "case_pack.csv"
CASES_DIR     = PROJECT_ROOT / "cases"
CASES_DIR.mkdir(parents=True, exist_ok=True)


def load_all_cases() -> List[Dict[str, Any]]:
    """Load all 20 cases from data/case_pack.csv."""
    if not CASE_PACK_CSV.exists():
        raise FileNotFoundError(f"case_pack.csv not found at {CASE_PACK_CSV}")

    df = pd.read_csv(CASE_PACK_CSV)
    cases = []
    for _, row in df.iterrows():
        score = float(row["risk_score"]) if pd.notna(row.get("risk_score")) and str(row.get("risk_score")).strip() else None
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


def run_single_case(case_info: Dict[str, Any]) -> Dict[str, Any]:
    """Execute investigation on a single benchmark case."""
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

    # Log quota and verdict summary
    llm = get_rate_limited_llm()
    rem = llm.calls_remaining
    verdict = result["case"]["verdict"]
    pattern = result["case"]["pattern"]
    exposure = result["case"]["exposure_usd"]
    sar_file = result["sar"]["file"]
    final_actions = [a["action"] for a in result["next_best_actions"]["final"]]

    logger.info(
        f"✔ Completed {cid} in {elapsed:.1f}s | Verdict: {verdict.upper()} | "
        f"Pattern: {pattern} | Exp: ${exposure:,.2f} | SAR: {sar_file} | "
        f"Actions: {final_actions} | Quota Remaining: {rem}"
    )
    return result


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

    print("\n" + "=" * 65)
    print("BENCHMARK DISTRIBUTION SANITY PASS (Anti-Overflagging Check)")
    print("=" * 65)
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
            "Competition specification warns: 'Half the cases are legitimate... An agent that blocks everything scores badly.' "
            "Consider reviewing borderline cases."
        )
    else:
        print(f"✅ SANITY CHECK PASSED: Balanced distribution ({legit_count} legitimate, {total - legit_count} fraud/uncertain).")
    print("=" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="HHGOA Fraud Investigation Benchmark Runner")
    parser.add_argument("--case", type=str, default=None, help="Run specific case, e.g. HHG-001")
    parser.add_argument("--all", action="store_true", default=True, help="Run all 20 cases")
    args = parser.parse_args()

    all_cases = load_all_cases()
    logger.info(f"Loaded {len(all_cases)} cases from {CASE_PACK_CSV}")

    if args.case:
        target = [c for c in all_cases if c["case_id"] == args.case]
        if not target:
            logger.error(f"Case {args.case} not found!")
            sys.exit(1)
        res = run_single_case(target[0])
        sanity_check_distribution([res])
        return

    # Run all 20 cases
    results = []
    print("\n" + "═" * 65)
    print("  HHGOA FRAUD INVESTIGATION BENCHMARK — RUNNING 20 CASES")
    print("═" * 65 + "\n")

    for i, c in enumerate(all_cases, 1):
        print(f"[{i:02d}/20] Processing {c['case_id']}...")
        res = run_single_case(c)
        results.append(res)

    sanity_check_distribution(results)
    print(f"All 20 answer files saved to {CASES_DIR}/")


if __name__ == "__main__":
    main()
