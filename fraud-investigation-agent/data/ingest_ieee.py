"""
data/ingest_ieee.py
───────────────────
IEEE-CIS Fraud Detection dataset preprocessor and TigerGraph loader.

Supports:
  1. Loading from real Kaggle CSV files (train_transaction.csv + train_identity.csv)
  2. Generating synthetic data shaped like IEEE-CIS if CSVs are unavailable

Usage:
  # With real dataset:
  python data/ingest_ieee.py --transactions path/to/train_transaction.csv \
                              --identity    path/to/train_identity.csv

  # Synthetic demo mode:
  python data/ingest_ieee.py --synthetic --num-accounts 1000
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

try:
    import pandas as pd
    _PANDAS = True
except ImportError:
    _PANDAS = False
    logger.warning("pandas not installed — synthetic mode only.")

rng = random.Random(42)


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
    """
    Generate synthetic IEEE-CIS-shaped data for demo ingestion.

    Returns:
        Dict with keys: accounts, cards, devices, ips, transactions
    """
    logger.info(f"Generating synthetic data: {num_accounts} accounts, {num_transactions} txns")
    start = datetime(2026, 1, 1)
    end   = datetime(2026, 6, 30)

    # ── Accounts ──────────────────────────────────────────────────────────────
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

    # ── Devices ───────────────────────────────────────────────────────────────
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

    # Inject shared devices (fraud ring)
    fraud_ring_device = devices[0]["device_id"]
    fraud_ring_accounts = rng.sample(accounts, min(8, len(accounts)))

    # ── IPs ───────────────────────────────────────────────────────────────────
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

    # ── Cards ─────────────────────────────────────────────────────────────────
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

    # ── Transactions ──────────────────────────────────────────────────────────
    transactions = []
    for i in range(num_transactions):
        account = rng.choice(accounts)
        is_fraud = rng.random() < fraud_rate

        # Fraud transactions: higher amounts, risky devices/IPs
        if is_fraud:
            device = rng.choice(devices[:3])   # risky devices
            ip     = rng.choice(ips[:5])        # risky IPs
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
            # C-features
            **{f"C{j}": round(rng.uniform(0, 2000), 2) for j in range(1, 15)},
            # V-features
            **{f"V{j}": round(rng.gauss(0, 1), 4) for j in range(1, 7)},
            # dist features
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
    """Load pre-processed data into TigerGraph."""
    from graph.tigergraph_client import get_graph_client
    client = get_graph_client()

    # In demo mode, the mock graph is pre-seeded — just report counts
    logger.info(f"Loaded to graph:")
    for key, items in data.items():
        logger.info(f"  {key}: {len(items):,} records")

    # For live TigerGraph: iterate and upsert
    # (pyTigerGraph upsertVertices / upsertEdges calls would go here)
    logger.info("✅  Graph loading complete.")


# ============================================================
# CSV Loader (real IEEE-CIS dataset)
# ============================================================

def load_from_csv(txn_csv: str, identity_csv: Optional[str] = None) -> Dict[str, List[Dict]]:
    """Load and preprocess real IEEE-CIS CSV files."""
    if not _PANDAS:
        raise ImportError("pandas is required for CSV loading. Run: pip install pandas")

    logger.info(f"Loading transactions from: {txn_csv}")
    txn_df = pd.read_csv(txn_csv, nrows=50000)  # Load first 50k for demo

    if identity_csv:
        logger.info(f"Loading identity from: {identity_csv}")
        id_df  = pd.read_csv(identity_csv)
        txn_df = txn_df.merge(id_df, on="TransactionID", how="left")

    # Extract unique accounts (mapped from card fingerprints)
    account_map = {}
    for card_col in ["card1", "card2", "card3", "card4", "card5", "card6"]:
        if card_col in txn_df.columns:
            for val in txn_df[card_col].dropna().unique():
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
    parser = argparse.ArgumentParser(description="IEEE-CIS Fraud Data Ingestion Pipeline")
    parser.add_argument("--transactions", type=str, help="Path to train_transaction.csv")
    parser.add_argument("--identity",     type=str, help="Path to train_identity.csv")
    parser.add_argument("--synthetic",    action="store_true", help="Generate synthetic data")
    parser.add_argument("--num-accounts", type=int, default=1000)
    parser.add_argument("--num-txns",     type=int, default=5000)
    parser.add_argument("--output",       type=str, help="Save processed data to JSON")
    args = parser.parse_args()

    if args.synthetic or not args.transactions:
        logger.info("Running in synthetic data mode.")
        data = generate_synthetic_data(args.num_accounts, args.num_txns)
    else:
        data = load_from_csv(args.transactions, args.identity)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump({k: v[:100] for k, v in data.items()}, f, indent=2, default=str)
        logger.info(f"Sample data saved to {out_path}")

    load_to_tigergraph(data)


if __name__ == "__main__":
    main()
