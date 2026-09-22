"""
data/generate_benchmark.py
──────────────────────────
Generates 20 realistic synthetic benchmark test cases
shaped like the IEEE-CIS Fraud Detection dataset.

Each case covers one of the 5 fraud typologies with varying
risk levels, evidence strengths, and expected outcomes.

Usage:  python data/generate_benchmark.py
Output: data/benchmark_cases/HHG-001.json ... HHG-020.json
"""
from __future__ import annotations

import json
import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

# Seeded for reproducibility
rng = random.Random(2026)

BASE_DIR    = Path(__file__).resolve().parent.parent
OUTPUT_DIR  = BASE_DIR / "data" / "benchmark_cases"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Typology configs ─────────────────────────────────────────────────────────

TYPOLOGY_CONFIGS = [
    # (typology, initial_risk_range, expected_action, sar_required)
    ("ACCOUNT_TAKEOVER",      (0.78, 0.95), "FREEZE_ACCOUNT",     True,  4),   # 4 cases
    ("CARD_NOT_PRESENT_RING", (0.72, 0.91), "BLOCK_TRANSACTION",  False, 4),   # 4 cases
    ("SYNTHETIC_IDENTITY",    (0.80, 0.97), "FILE_SAR",           True,  4),   # 4 cases
    ("SMURFING_VELOCITY",     (0.75, 0.93), "FILE_SAR",           True,  4),   # 4 cases
    ("BUST_OUT",              (0.68, 0.88), "ACCOUNT_HOLD",       False, 4),   # 4 cases
]


def _rand_account_id() -> str:
    return f"ACC_{rng.randint(100000, 999999)}"

def _rand_device_id() -> str:
    return f"DEV_{rng.randint(1000, 9999)}"

def _rand_ip(country: str = "US") -> str:
    if country == "RU":
        return f"5.{rng.randint(1,255)}.{rng.randint(1,255)}.{rng.randint(1,255)}"
    elif country == "NG":
        return f"197.{rng.randint(1,255)}.{rng.randint(1,255)}.{rng.randint(1,255)}"
    return f"{rng.randint(1,255)}.{rng.randint(1,255)}.{rng.randint(1,255)}.{rng.randint(1,255)}"

def _rand_txn_id() -> str:
    return f"TXN_{rng.randint(1000000, 9999999)}"

def _rand_ts(offset_hours: int = 0) -> str:
    base = datetime(2026, rng.randint(1, 6), rng.randint(1, 28),
                    rng.randint(0, 23), rng.randint(0, 59))
    return (base - timedelta(hours=offset_hours)).isoformat() + "Z"


def _ieee_features() -> Dict[str, Any]:
    """Generate realistic IEEE-CIS-shaped feature vectors."""
    return {
        # C-features (count-based)
        **{f"C{i}": round(rng.uniform(0, 2000), 2) for i in range(1, 15)},
        # V-features (Vesta risk)
        **{f"V{i}": round(rng.gauss(0, 1), 4) for i in range(1, 7)},
        # D-features (time deltas in days)
        **{f"D{i}": round(rng.uniform(0, 400), 1) for i in range(1, 6)},
        # M-features (match flags)
        **{f"M{i}": rng.choice(["T", "F"]) for i in range(1, 10)},
        # Identity features
        "id_01": round(rng.uniform(-5, 5), 1),
        "id_02": round(rng.uniform(100, 300), 1),
        "id_12": rng.choice(["Found", "NotFound"]),
        "id_15": rng.choice(["New", "Found", "Unknown"]),
        "id_28": rng.choice(["New", "Found"]),
        "id_31": f"chrome {rng.randint(80,120)}.0",
        "DeviceType": rng.choice(["desktop", "mobile", "tablet"]),
        "DeviceInfo": rng.choice(["Windows 10", "MacOS", "iOS 17", "Android 14"]),
        "dist1": round(rng.uniform(0, 500), 1),
        "dist2": round(rng.uniform(0, 3000), 1),
        "ProductCD": rng.choice(["W", "H", "C", "S", "R"]),
    }


def _generate_ato_case(case_num: int) -> Dict[str, Any]:
    """Account Takeover scenario."""
    acct       = _rand_account_id()
    new_device = _rand_device_id()
    foreign_ip = _rand_ip("RU")
    txn_id     = _rand_txn_id()
    amount     = round(rng.uniform(3500, 18000), 2)
    init_risk  = round(rng.uniform(0.78, 0.95), 4)

    return {
        "case_id": f"CASE_2026_{case_num:03d}",
        "typology": "ACCOUNT_TAKEOVER",
        "initial_trigger": {
            "account_id":    acct,
            "transaction_id": txn_id,
            "trigger_type":  "HIGH_RISK_SCORE",
            "initial_risk":  init_risk,
            "amount":        amount,
            "timestamp":     _rand_ts(2),
        },
        "graph_scenario": {
            "new_device_detected": True,
            "device_id":           new_device,
            "ip_address":          foreign_ip,
            "ip_country":          "RU",
            "ip_proxy":            True,
            "shared_device_accounts": [],
            "shared_ip_accounts":  [_rand_account_id()],
            "velocity_burst_score": round(rng.uniform(2, 6), 2),
            "ring_size":           0,
        },
        "features": _ieee_features(),
        "expected": {
            "fraud_typology":    "ACCOUNT_TAKEOVER",
            "pre_evidence_action": "STEP_UP_AUTH",
            "post_evidence_action": "FREEZE_ACCOUNT",
            "sar_required":      init_risk >= 0.85,
            "approval_tier":     "TIER_2_ANALYST",
        },
    }


def _generate_cnp_case(case_num: int) -> Dict[str, Any]:
    """Card-Not-Present Ring scenario."""
    acct        = _rand_account_id()
    shared_dev  = _rand_device_id()
    linked_accs = [_rand_account_id() for _ in range(rng.randint(3, 6))]
    txn_id      = _rand_txn_id()
    amount      = round(rng.uniform(800, 5000), 2)
    init_risk   = round(rng.uniform(0.72, 0.91), 4)

    return {
        "case_id": f"CASE_2026_{case_num:03d}",
        "typology": "CARD_NOT_PRESENT_RING",
        "initial_trigger": {
            "account_id":    acct,
            "transaction_id": txn_id,
            "trigger_type":  "PATTERN_MATCH",
            "initial_risk":  init_risk,
            "amount":        amount,
            "timestamp":     _rand_ts(1),
        },
        "graph_scenario": {
            "new_device_detected": False,
            "device_id":           shared_dev,
            "ip_address":          _rand_ip("US"),
            "ip_country":          "US",
            "ip_proxy":            rng.random() > 0.5,
            "shared_device_accounts": linked_accs,
            "shared_ip_accounts":  linked_accs[:2],
            "velocity_burst_score": round(rng.uniform(4, 12), 2),
            "ring_size":           len(linked_accs) + 1,
        },
        "features": _ieee_features(),
        "expected": {
            "fraud_typology":    "CARD_NOT_PRESENT_RING",
            "pre_evidence_action": "STEP_UP_AUTH",
            "post_evidence_action": "BLOCK_TRANSACTION",
            "sar_required":      False,
            "approval_tier":     "TIER_2_ANALYST",
        },
    }


def _generate_synth_case(case_num: int) -> Dict[str, Any]:
    """Synthetic Identity Fraud scenario."""
    acct       = _rand_account_id()
    ring_accs  = [_rand_account_id() for _ in range(rng.randint(5, 9))]
    shared_dev = _rand_device_id()
    txn_id     = _rand_txn_id()
    amount     = round(rng.uniform(5000, 25000), 2)
    init_risk  = round(rng.uniform(0.80, 0.97), 4)

    return {
        "case_id": f"CASE_2026_{case_num:03d}",
        "typology": "SYNTHETIC_IDENTITY",
        "initial_trigger": {
            "account_id":    acct,
            "transaction_id": txn_id,
            "trigger_type":  "HIGH_RISK_SCORE",
            "initial_risk":  init_risk,
            "amount":        amount,
            "timestamp":     _rand_ts(0),
        },
        "graph_scenario": {
            "new_device_detected": True,
            "device_id":           shared_dev,
            "ip_address":          _rand_ip("NG"),
            "ip_country":          "NG",
            "ip_proxy":            True,
            "shared_device_accounts": ring_accs,
            "shared_ip_accounts":  ring_accs[:3],
            "velocity_burst_score": round(rng.uniform(8, 20), 2),
            "ring_size":           len(ring_accs) + 1,
        },
        "features": _ieee_features(),
        "expected": {
            "fraud_typology":    "SYNTHETIC_IDENTITY",
            "pre_evidence_action": "STEP_UP_AUTH",
            "post_evidence_action": "FILE_SAR",
            "sar_required":      True,
            "approval_tier":     "COMPLIANCE_OFFICER",
        },
    }


def _generate_smurfing_case(case_num: int) -> Dict[str, Any]:
    """Smurfing / Structuring scenario."""
    acct      = _rand_account_id()
    txn_id    = _rand_txn_id()
    # Multiple sub-threshold transactions
    txns      = [
        {"txn_id": _rand_txn_id(), "amount": round(rng.uniform(8800, 9999), 2), "ts": _rand_ts(i)}
        for i in range(rng.randint(8, 15))
    ]
    init_risk = round(rng.uniform(0.75, 0.93), 4)

    return {
        "case_id": f"CASE_2026_{case_num:03d}",
        "typology": "SMURFING_VELOCITY",
        "initial_trigger": {
            "account_id":    acct,
            "transaction_id": txn_id,
            "trigger_type":  "VELOCITY_SPIKE",
            "initial_risk":  init_risk,
            "amount":        sum(t["amount"] for t in txns),
            "timestamp":     _rand_ts(0),
        },
        "graph_scenario": {
            "new_device_detected": False,
            "device_id":           _rand_device_id(),
            "ip_address":          _rand_ip("US"),
            "ip_country":          "US",
            "ip_proxy":            False,
            "shared_device_accounts": [],
            "shared_ip_accounts":  [],
            "velocity_burst_score": round(rng.uniform(15, 30), 2),
            "ring_size":           0,
            "sub_transactions":    txns,
        },
        "features": _ieee_features(),
        "expected": {
            "fraud_typology":    "SMURFING_VELOCITY",
            "pre_evidence_action": "ADD_TO_WATCHLIST",
            "post_evidence_action": "FILE_SAR",
            "sar_required":      True,
            "approval_tier":     "COMPLIANCE_OFFICER",
        },
    }


def _generate_bustout_case(case_num: int) -> Dict[str, Any]:
    """Bust-Out Fraud scenario."""
    acct      = _rand_account_id()
    txn_id    = _rand_txn_id()
    amount    = round(rng.uniform(10000, 45000), 2)
    init_risk = round(rng.uniform(0.68, 0.88), 4)

    return {
        "case_id": f"CASE_2026_{case_num:03d}",
        "typology": "BUST_OUT",
        "initial_trigger": {
            "account_id":    acct,
            "transaction_id": txn_id,
            "trigger_type":  "HIGH_RISK_SCORE",
            "initial_risk":  init_risk,
            "amount":        amount,
            "timestamp":     _rand_ts(3),
        },
        "graph_scenario": {
            "new_device_detected": False,
            "device_id":           _rand_device_id(),
            "ip_address":          _rand_ip("US"),
            "ip_country":          "US",
            "ip_proxy":            False,
            "shared_device_accounts": [_rand_account_id()],
            "shared_ip_accounts":  [],
            "velocity_burst_score": round(rng.uniform(5, 12), 2),
            "ring_size":           0,
            "account_age_days":    rng.randint(30, 180),
            "credit_utilization":  round(rng.uniform(0.85, 1.0), 3),
        },
        "features": _ieee_features(),
        "expected": {
            "fraud_typology":    "BUST_OUT",
            "pre_evidence_action": "STEP_UP_AUTH",
            "post_evidence_action": "ACCOUNT_HOLD",
            "sar_required":      init_risk >= 0.85,
            "approval_tier":     "TIER_2_ANALYST",
        },
    }


# ─── Generator dispatch ───────────────────────────────────────────────────────

GENERATORS = {
    "ACCOUNT_TAKEOVER":      _generate_ato_case,
    "CARD_NOT_PRESENT_RING": _generate_cnp_case,
    "SYNTHETIC_IDENTITY":    _generate_synth_case,
    "SMURFING_VELOCITY":     _generate_smurfing_case,
    "BUST_OUT":              _generate_bustout_case,
}


def generate_all_cases() -> List[Dict[str, Any]]:
    """Generate all 20 benchmark test cases."""
    cases = []
    case_num = 1

    for typology, _, _, _, count in TYPOLOGY_CONFIGS:
        gen_fn = GENERATORS[typology]
        for _ in range(count):
            case = gen_fn(case_num)
            cases.append(case)

            # Save individual file
            out_path = OUTPUT_DIR / f"HHG-{case_num:03d}.json"
            with open(out_path, "w") as f:
                json.dump(case, f, indent=2, default=str)

            print(f"  ✓ HHG-{case_num:03d}.json  [{typology}]  risk={case['initial_trigger']['initial_risk']:.3f}")
            case_num += 1

    # Save index file
    index_path = OUTPUT_DIR / "index.json"
    with open(index_path, "w") as f:
        json.dump(
            [{"case_id": c["case_id"], "typology": c["typology"],
              "initial_risk": c["initial_trigger"]["initial_risk"]}
             for c in cases],
            f, indent=2
        )

    return cases


if __name__ == "__main__":
    print(f"Generating 20 benchmark cases -> {OUTPUT_DIR}")
    cases = generate_all_cases()
    print(f"\n✅  {len(cases)} benchmark cases generated successfully.")
    print(f"    Index: {OUTPUT_DIR / 'index.json'}")
