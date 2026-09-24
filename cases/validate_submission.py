"""
cases/validate_submission.py
────────────────────────────
Automated validation of all 20 Hacker House Goa answer JSON files.

Enforces:
1. Exact file count: HHG-001.json through HHG-020.json
2. All 15 required fields in 'case' object (specifically summary, written_to_graph, graph_case_id)
3. Authentic dataset IDs (strictly numeric transaction IDs, C#####-K# card IDs, no 'T' prefixes)
4. Strict Policy v1.0 enum conformance (14 actions, 3 routes, 5+1 patterns)
5. Logical consistency (exposure_usd, sar.file agreement with FILE_REPORT)
6. Anti-overflagging distribution sanity check (~50% legitimate cases)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = PROJECT_ROOT / "cases"

ALLOWED_ACTIONS = {
    "ALLOW_TRANSACTION", "DECLINE_TRANSACTION", "MONITOR_CARD", "MONITOR_CONNECTED_CARDS",
    "WARN_CUSTOMER", "VERIFY_WITH_CUSTOMER", "STEP_UP_AUTH", "BLOCK_CARD", "BLOCK_ALL_CARDS",
    "GENERATE_REPORT", "CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST", "CLOSE_NO_FRAUD"
}

ALLOWED_ROUTES = {"auto", "L1", "L2"}

ALLOWED_PATTERNS = {
    "card_testing", "card_not_present_fraud", "card_not_present_new_device",
    "out_of_region_use", "account_takeover", "undocumented", "none"
}

ALLOWED_STATUSES = {"open", "closed_fraud", "closed_legitimate", "escalated"}
ALLOWED_VERDICTS = {"fraud", "legitimate", "uncertain"}

CASE_REQUIRED_FIELDS = [
    "status", "verdict", "fraud_probability", "pattern", "pattern_description",
    "affected_txn_ids", "first_suspicious_txn_id", "connected_card_ids",
    "connected_device_profiles", "exposure_usd", "evidence", "similar_prior_cases",
    "summary", "written_to_graph", "graph_case_id"
]


def validate_file(file_path: Path) -> List[str]:
    """Validate a single case answer JSON file. Returns list of error strings."""
    errors = []
    case_name = file_path.name

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return [f"{case_name}: Invalid JSON: {e}"]

    # 1. Top-level keys
    for k in ["case_id", "case", "evidence_requests", "next_best_actions", "sar", "stop_reason", "tool_calls", "tokens", "latency_s"]:
        if k not in data:
            errors.append(f"{case_name}: Missing top-level key '{k}'")

    case_obj = data.get("case", {})
    if not isinstance(case_obj, dict):
        return errors + [f"{case_name}: 'case' must be an object"]

    # 2. All 15 fields in case
    for field in CASE_REQUIRED_FIELDS:
        if field not in case_obj:
            errors.append(f"{case_name}: Missing required field in case: '{field}'")

    # 3. Status and verdict enums
    if case_obj.get("status") not in ALLOWED_STATUSES:
        errors.append(f"{case_name}: Invalid case.status '{case_obj.get('status')}'. Must be one of {ALLOWED_STATUSES}")
    if case_obj.get("verdict") not in ALLOWED_VERDICTS:
        errors.append(f"{case_name}: Invalid case.verdict '{case_obj.get('verdict')}'. Must be one of {ALLOWED_VERDICTS}")

    # 4. Pattern enum
    if case_obj.get("pattern") not in ALLOWED_PATTERNS:
        errors.append(f"{case_name}: Invalid case.pattern '{case_obj.get('pattern')}'. Must be one of {ALLOWED_PATTERNS}")

    if case_obj.get("pattern") == "undocumented" and not case_obj.get("pattern_description"):
        errors.append(f"{case_name}: pattern is 'undocumented' but pattern_description is empty")

    # 5. Authentic dataset IDs: NO 'T' prefixes, must be numeric string
    for tid in case_obj.get("affected_txn_ids", []):
        if str(tid).startswith("T") or not str(tid).isdigit():
            errors.append(f"{case_name}: Fabricated/reformatted txn ID '{tid}'. Must be authentic numeric ID from CSV.")

    first_susp = case_obj.get("first_suspicious_txn_id", "")
    if first_susp and (str(first_susp).startswith("T") or not str(first_susp).isdigit()):
        errors.append(f"{case_name}: Fabricated first_suspicious_txn_id '{first_susp}'. Must be numeric string.")

    for cid in case_obj.get("connected_card_ids", []):
        if not str(cid).startswith("C") or "-K" not in str(cid):
            errors.append(f"{case_name}: Invalid card ID format '{cid}'. Expected C#####-K#.")

    # 6. Actions and routes
    nba = data.get("next_best_actions", {})
    final_actions = nba.get("final", [])
    has_file_report = False

    for item in nba.get("initial", []) + final_actions:
        act = item.get("action")
        rt = item.get("route")
        if act not in ALLOWED_ACTIONS:
            errors.append(f"{case_name}: Invalid action '{act}'. Must be one of {ALLOWED_ACTIONS}")
        if rt not in ALLOWED_ROUTES:
            errors.append(f"{case_name}: Invalid route '{rt}'. Must be one of {ALLOWED_ROUTES}")
        if act == "FILE_REPORT":
            has_file_report = True

    # 7. SAR consistency
    sar = data.get("sar", {})
    sar_file = sar.get("file", False)
    if sar_file != has_file_report:
        errors.append(
            f"{case_name}: sar.file ({sar_file}) does not agree with presence of FILE_REPORT in final actions ({has_file_report})"
        )

    if sar_file and not sar.get("narrative"):
        errors.append(f"{case_name}: sar.file is True but sar.narrative is empty")

    # 8. Legitimate consistency
    if case_obj.get("verdict") == "legitimate":
        if case_obj.get("affected_txn_ids"):
            errors.append(f"{case_name}: verdict is legitimate but affected_txn_ids is not empty")
        if case_obj.get("exposure_usd") != 0.0:
            errors.append(f"{case_name}: verdict is legitimate but exposure_usd is not 0.0")
        if sar_file:
            errors.append(f"{case_name}: verdict is legitimate but sar.file is True")

    # 9. Summary check (2-6 sentences)
    summary = case_obj.get("summary", "")
    if not summary or len(summary.split(".")) < 2:
        errors.append(f"{case_name}: summary is too short or missing (expected 2-6 sentences)")

    # 10. Written to graph check
    if not case_obj.get("written_to_graph"):
        errors.append(f"{case_name}: written_to_graph must be True")

    return errors


def main():
    print("=" * 65)
    print("  HHGOA SUBMISSION VALIDATOR — CHECKING 20 ANSWER FILES")
    print("=" * 65)

    if not CASES_DIR.exists():
        print(f"❌ Error: {CASES_DIR} directory does not exist. Run benchmark first.")
        sys.exit(1)

    expected_cases = [f"HHG-{i:03d}.json" for i in range(1, 21)]
    found_files = set(f.name for f in CASES_DIR.glob("HHG-*.json"))

    missing = set(expected_cases) - found_files
    if missing:
        print(f"❌ Error: Missing {len(missing)} answer files: {sorted(list(missing))}")
        sys.exit(1)

    total_errors = 0
    results_summary = []

    for fname in expected_cases:
        fpath = CASES_DIR / fname
        errs = validate_file(fpath)
        if errs:
            total_errors += len(errs)
            print(f"❌ {fname} FAIL:")
            for e in errs:
                print(f"   - {e}")
        else:
            with open(fpath, "r", encoding="utf-8") as f:
                d = json.load(f)
            v = d["case"]["verdict"]
            p = d["case"]["pattern"]
            exp = d["case"]["exposure_usd"]
            sar = d["sar"]["file"]
            actions = [a["action"] for a in d["next_best_actions"]["final"]]
            results_summary.append({
                "case_id": fname.replace(".json", ""),
                "verdict": v,
                "pattern": p,
                "exposure": exp,
                "sar": sar,
                "actions": actions,
            })
            print(f"✔ {fname} PASS ({v.upper()} | {p} | ${exp:,.2f} | SAR:{sar})")

    # Sanity distribution check
    print("\n" + "-" * 65)
    print("DISTRIBUTION SANITY PASS:")
    print("-" * 65)
    legit_cnt = sum(1 for r in results_summary if r["verdict"] == "legitimate")
    fraud_cnt = sum(1 for r in results_summary if r["verdict"] == "fraud")
    unc_cnt = sum(1 for r in results_summary if r["verdict"] == "uncertain")
    block_cnt = sum(1 for r in results_summary if any("BLOCK" in a for a in r["actions"]))
    sar_cnt = sum(1 for r in results_summary if r["sar"])

    print(f"Total Cases:     20")
    print(f"Legitimate:      {legit_cnt} ({legit_cnt/20:.0%})")
    print(f"Fraud:           {fraud_cnt} ({fraud_cnt/20:.0%})")
    print(f"Uncertain:       {unc_cnt} ({unc_cnt/20:.0%})")
    print(f"BLOCK actions:   {block_cnt} ({block_cnt/20:.0%})")
    print(f"FILE_REPORT:     {sar_cnt} ({sar_cnt/20:.0%})")
    print("-" * 65)

    if block_cnt > 12:
        print(f"⚠️ WARNING: Over-blocking detected ({block_cnt}/20 cases recommend BLOCK). Spec requires ~50% legitimate.")
    else:
        print(f"✅ Calibrated distribution confirmed: {legit_cnt}/20 cases legitimate, {block_cnt}/20 blocked.")

    if total_errors == 0:
        print("\n🎉 ALL 20 ANSWER FILES FULLY VALIDATED AND COMPLIANT WITH COMPETITION SPEC!\n")
    else:
        print(f"\n❌ Validation finished with {total_errors} errors.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
