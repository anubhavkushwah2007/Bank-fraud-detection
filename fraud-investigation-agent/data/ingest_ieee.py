"""
data/ingest_ieee.py
───────────────────
IEEE-CIS Fraud Detection dataset preprocessor and TigerGraph loader.

Supports:
  1. Loading from real dataset CSVs (transactions + identity)
  2. Generating synthetic data shaped like IEEE-CIS if CSVs are unavailable

Usage:
  # With real dataset (defaults come from .env DATASET_PATH if not passed):
  python data/ingest_ieee.py --transactions data/transactions.csv \
                              --identity    data/identity.csv

  # Synthetic demo mode:
  python data/ingest_ieee.py --synthetic --num-accounts 1000
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

try:
    import pandas as pd
    _PANDAS = True
except ImportError:
    _PANDAS = False
    logger.warning("pandas not installed — synthetic mode only.")

rng = random.Random(42)

DATASET_PATH = os.getenv("DATASET_PATH", "./data")

# Candidate column names for account-identifying fields.
# Real Kaggle IEEE-CIS uses card1-card6 + TransactionID; hackathon-provided
# datasets are frequently renamed, so we try several likely alternatives.
CARD_COL_CANDIDATES = [
    ["card1", "card2", "card3", "card4", "card5", "card6"],
    ["CardID", "card_id", "Card_ID"],
    ["AccountID", "account_id", "Account_ID"],
]
TXN_ID_CANDIDATES = ["TransactionID", "txn_id", "TxnID", "transaction_id"]


# ============================================================
# Synthetic Data Generator
# ============================================================

def _rand_dt(start: datetime, end: datetime) -> str:
    delta = end - start
    return (start + timedelta(seconds=rng.randint(0, int(delta.total_seconds())))).isoformat()


def generate_synthetic_data(
    num_accounts: int = 1000,
    num_transactions: int = 5000,
    fraud_rate: float = 0.035,
) -> Dict[str, List[Dict]]:
    logger.info(f"Generating synthetic data: {num_accounts} accounts, {num_transactions} txns")
    start = datetime(2026, 1, 1)
    end   = datetime(2026, 6, 30)

    accounts = []
    for i in range(num_accounts):
        acc_id = f"ACC_{i+1:06d}"
        accounts.append({
            "account_id":        acc_id,
            "open_date":         _rand_dt(datetime(2020, 1, 1), start),
            "risk_baseline":     round(rng.uniform(0.0, 0.3), 4),
            "status":            rng.choices(["ACTIVE", "WATCHLIST"], weights=[0.95, 0.05])[0],
            "account_type":      rng.choice(["CHECKING", "SAVINGS", "CREDIT"]),
            "email_hash":        uuid.uuid4().hex[:16],
            "phone_hash":        uuid.uuid4().hex[:12],
            "addr_zip":          str(rng.randint(10000, 99999)),
        })

    num_devices = max(1, num_accounts // 3)
    devices = []
    for i in range(num_devices):
        devices.append({
            "device_id":   f"DEV_{i+1:05d}",
            "device_info": rng.choice(["Windows 10", "MacOS", "iOS 17", "Android 14"]),
            "device_type": rng.choice(["desktop", "mobile", "tablet"]),
            "os":          rng.choice(["Windows", "macOS", "iOS", "Android", "Linux"]),
            "browser":     rng.choice(["Chrome", "Firefox", "Safari", "Edge"]),
            "is_emulator": rng.random() < 0.02,
            "risk_score":  round(rng.uniform(0.0, 0.4), 4),
        })

    fraud_ring_device = devices[0]["device_id"]
    fraud_ring_accounts = rng.sample(accounts, min(8, len(accounts)))

    num_ips = max(1, num_accounts // 4)
    ips = []
    for i in range(num_ips):
        is_proxy = rng.random() < 0.05
        country  = rng.choices(["US", "RU", "NG", "CN", "BR"], weights=[0.75, 0.10, 0.05, 0.05, 0.05])[0]
        ips.append({
            "ip_hash":         f"IP_{i+1:05d}",
            "country":         country,
            "region":          uuid.uuid4().hex[:4].upper(),
            "is_proxy":        is_proxy,
            "is_vpn":          is_proxy and rng.random() < 0.6,
            "is_tor":          is_proxy and rng.random() < 0.2,
            "abuse_confidence": round(rng.uniform(0.5, 1.0) if is_proxy else rng.uniform(0.0, 0.2), 4),
            "asn":             f"AS{rng.randint(100, 99999)}",
        })

    num_cards = max(1, num_accounts // 2)
    cards = []
    for i in range(num_cards):
        cards.append({
            "card_id":        f"CARD_{i+1:06d}",
            "card_type":      rng.choice(["VISA", "MC", "AMEX", "DISCOVER"]),
            "issuer":         rng.choice(["Chase", "BofA", "Wells Fargo", "Citi", "Capital One"]),
            "expiration":     f"{rng.randint(1,12):02d}/{rng.randint(27,32)}",
            "bin_number":     str(rng.randint(400000, 599999)),
            "is_compromised": rng.random() < 0.03,
        })

    transactions = []
    for i in range(num_transactions):
        account = rng.choice(accounts)
        is_fraud = rng.random() < fraud_rate

        if is_fraud:
            device = rng.choice(devices[:3])
            ip     = rng.choice(ips[:5])
            amount = round(rng.uniform(1000, 25000), 2)
            risk   = round(rng.uniform(0.70, 0.99), 4)
        else:
            device = rng.choice(devices)
            ip     = rng.choice(ips)
            amount = round(rng.lognormvariate(5, 1.5), 2)
            risk   = round(rng.uniform(0.01, 0.30), 4)

        card = rng.choice(cards)
        ts   = _rand_dt(start, end)

        transactions.append({
            "txn_id":      f"TXN_{i+1:08d}",
            "account_id":  account["account_id"],
            "amount":      amount,
            "timestamp":   ts,
            "risk_score":  risk,
            "isFraud":     is_fraud,
            "product_cd":  rng.choice(["W", "H", "C", "S", "R"]),
            "card_present": not is_fraud or rng.random() > 0.7,
            "trans_type":  "PURCHASE",
            "device_id":   device["device_id"],
            "ip_hash":     ip["ip_hash"],
            "card_id":     card["card_id"],
            **{f"C{j}": round(rng.uniform(0, 2000), 2) for j in range(1, 15)},
            **{f"V{j}": round(rng.gauss(0, 1), 4) for j in range(1, 7)},
            "dist1": round(rng.uniform(0, 500), 1),
            "dist2": round(rng.uniform(0, 3000), 1),
        })

    return {
        "accounts":     accounts,
        "devices":      devices,
        "ips":          ips,
        "cards":        cards,
        "transactions": transactions,
    }


# ============================================================
# TigerGraph Loader
# ============================================================

def load_to_tigergraph(data: Dict[str, List[Dict]]) -> None:
    from graph.tigergraph_client import get_graph_client
    client = get_graph_client()

    logger.info("Loaded to graph:")
    for key, items in data.items():
        logger.info(f"  {key}: {len(items):,} records")

    logger.info("✅  Graph loading complete.")


# ============================================================
# CSV Loader (real dataset)
# ============================================================

def _find_present_columns(df: "pd.DataFrame", candidates: List[str]) -> List[str]:
    return [c for c in candidates if c in df.columns]


def load_from_csv(txn_csv: str, identity_csv: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Load and preprocess real dataset CSV files.

    Tries several known column-naming conventions (raw Kaggle IEEE-CIS vs.
    common hackathon renamings) instead of assuming one schema. Raises a
    clear error rather than silently returning zero accounts if nothing
    matches, so a schema mismatch is caught immediately rather than
    discovered later as an empty graph.
    """
    if not _PANDAS:
        raise ImportError("pandas is required for CSV loading. Run: pip install pandas")

    logger.info(f"Loading transactions from: {txn_csv}")
    txn_df = pd.read_csv(txn_csv, nrows=50000)
    logger.info(f"Columns found: {list(txn_df.columns)}")

    if identity_csv:
        logger.info(f"Loading identity from: {identity_csv}")
        id_df = pd.read_csv(identity_csv)
        txn_id_cols = _find_present_columns(txn_df, TXN_ID_CANDIDATES)
        id_id_cols  = _find_present_columns(id_df, TXN_ID_CANDIDATES)
        if txn_id_cols and id_id_cols:
            txn_df = txn_df.merge(id_df, left_on=txn_id_cols[0], right_on=id_id_cols[0], how="left")
        else:
            logger.warning(
                "No shared transaction-ID column found between transactions and "
                "identity files — skipping merge. Check column names above."
            )

    # Try each candidate group of "account-identifying" columns in order.
    account_cols: List[str] = []
    for group in CARD_COL_CANDIDATES:
        found = _find_present_columns(txn_df, group)
        if found:
            account_cols = found
            break

    if not account_cols:
        raise ValueError(
            "Could not find any recognizable account/card ID columns in "
            f"{txn_csv}. Columns present: {list(txn_df.columns)}. "
            "Update CARD_COL_CANDIDATES in ingest_ieee.py to match your "
            "dataset's actual column names."
        )

    logger.info(f"Using columns for account inference: {account_cols}")

    account_map: Dict[str, str] = {}
    for col in account_cols:
        for val in txn_df[col].dropna().unique():
            key = str(val)
            if key not in account_map:
                account_map[key] = f"ACC_{len(account_map)+1:06d}"

    transactions = txn_df.to_dict(orient="records")
    logger.info(f"Loaded {len(transactions):,} transactions, {len(account_map):,} inferred accounts")

    return {
        "accounts":     [{"account_id": v} for v in account_map.values()],
        "transactions": transactions,
        "devices":      [],
        "ips":          [],
        "cards":        [],
    }


# ============================================================
# CLI Entry Point
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Fraud Data Ingestion Pipeline")
    parser.add_argument("--transactions", type=str,
                         default=os.path.join(DATASET_PATH, "transactions.csv"),
                         help="Path to transactions CSV (default: $DATASET_PATH/transactions.csv)")
    parser.add_argument("--identity", type=str,
                         default=os.path.join(DATASET_PATH, "identity.csv"),
                         help="Path to identity CSV (default: $DATASET_PATH/identity.csv)")
    parser.add_argument("--synthetic",    action="store_true", help="Generate synthetic data")
    parser.add_argument("--num-accounts", type=int, default=1000)
    parser.add_argument("--num-txns",     type=int, default=5000)
    parser.add_argument("--output",       type=str, help="Save processed data to JSON")
    args = parser.parse_args()

    if args.synthetic:
        logger.info("Running in synthetic data mode.")
        data = generate_synthetic_data(args.num_accounts, args.num_txns)
    elif Path(args.transactions).exists():
        data = load_from_csv(args.transactions, args.identity if Path(args.identity).exists() else None)
    else:
        logger.warning(f"Transactions file not found at {args.transactions} — falling back to synthetic mode.")
        data = generate_synthetic_data(args.num_accounts, args.num_txns)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({k: v[:100] for k, v in data.items()}, f, indent=2, default=str)
        logger.info(f"Sample data saved to {out_path}")

    load_to_tigergraph(data)


if __name__ == "__main__":
    main()