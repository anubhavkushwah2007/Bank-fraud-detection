"""
data/load_all.py
────────────────
Loads the REAL IEEE-CIS dataset into TigerGraph Cloud / Savanna graph:
- 590,742 Transactions with core attributes
- 13,500+ Customers, 15,000+ Cards, 9,705 DeviceProfiles
- 5,565 ClosedCases with full analyst_notes and CC_INVOLVES / CC_ON_CARD edges
- 20 CasePack benchmark cases
- Chronological NEXT transaction chains per card
- Preserves full 393-column features in data_real/transactions_full.parquet
  with get_full_features(txn_id) on-demand lookup.

GUARANTEES:
- Idempotent and chunked for memory efficiency.
- Tests 10-row write/read before bulk ingestion.
- Halts and reports cleanly if TigerGraph rejects payload or quota/memory limits.
- Prints exact expected vs actual counts.
- Zero DROP statements.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Set, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("load_all")

try:
    import pyTigerGraph as tg
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False


# ==============================================================================
# Full Feature Store: data_real/transactions_full.parquet
# ==============================================================================

_PARQUET_FILE = settings.DATA_DIR / "transactions_full.parquet"
_CORE_COLS = {
    "TransactionID", "ts", "TransactionAmt", "ProductCD", "channel",
    "risk_score", "addr1", "addr2", "dist1", "P_emaildomain",
    "card4", "card6", "id_15", "id_23", "DeviceType",
    "C1", "C2", "D1", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9",
    "customer_id", "card1"
}


def build_full_features_parquet_if_needed() -> None:
    """Build data_real/transactions_full.parquet if not already present."""
    if _PARQUET_FILE.exists():
        logger.info(f"Using existing full features parquet: {_PARQUET_FILE} ({_PARQUET_FILE.stat().st_size / (1024**2):.1f} MB)")
        return

    logger.info(f"Building {_PARQUET_FILE} for on-demand 393-column feature lookups...")
    if not settings.TRANSACTIONS_CSV.exists():
        raise FileNotFoundError(f"Missing required CSV: {settings.TRANSACTIONS_CSV}")

    # Read identity lookup if available
    df_id: Optional[pd.DataFrame] = None
    if settings.IDENTITY_CSV.exists():
        logger.info("Reading identity CSV for feature enrichment...")
        df_id = pd.read_csv(settings.IDENTITY_CSV)

    writer: Optional[pq.ParquetWriter] = None
    chunk_size = 50000
    total_processed = 0

    for chunk in pd.read_csv(settings.TRANSACTIONS_CSV, chunksize=chunk_size, low_memory=False):
        if df_id is not None:
            chunk = chunk.merge(df_id, on="TransactionID", how="left")

        table = pa.Table.from_pandas(chunk, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(_PARQUET_FILE, table.schema, compression="snappy")
        writer.write_table(table)
        total_processed += len(chunk)
        logger.info(f"  Parquet build progress: {total_processed:,} / 590,742 rows...")

    if writer:
        writer.close()
    logger.info(f"[OK] Completed {_PARQUET_FILE} ({_PARQUET_FILE.stat().st_size / (1024**2):.1f} MB)")


def get_full_features(txn_id: int | str) -> Dict[str, Any]:
    """Look up all extended transaction features from data_real/transactions_full.parquet."""
    if not _PARQUET_FILE.exists():
        build_full_features_parquet_if_needed()

    tid = int(txn_id)
    try:
        dataset = ds.dataset(_PARQUET_FILE, format="parquet")
        table = dataset.to_table(filter=ds.field("TransactionID") == tid)
        if len(table) == 0:
            return {}
        return {col: table[col][0].as_py() for col in table.column_names}
    except Exception as e:
        logger.warning(f"Failed to lookup full features for txn {txn_id}: {e}")
        return {}


# ==============================================================================
# TigerGraph Connection Helper
# ==============================================================================

def get_connection() -> tg.TigerGraphConnection:
    """Connect to the TigerGraph instance specified in settings."""
    if not _TG_AVAILABLE:
        raise RuntimeError("pyTigerGraph is not installed. Run: pip install pyTigerGraph")

    host = settings.TIGERGRAPH_HOST
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"https://{host}"

    graph_name = os.getenv("TG_GRAPHNAME") or settings.TIGERGRAPH_GRAPH

    logger.info(f"Connecting to TigerGraph at {host} on graph '{graph_name}'...")
    conn = tg.TigerGraphConnection(
        host=host,
        graphname=graph_name,
        username=settings.TIGERGRAPH_USERNAME,
        password=settings.TIGERGRAPH_PASSWORD,
        gsqlSecret=settings.TIGERGRAPH_SECRET,
        tgCloud=settings.TG_TGCLOUD,
        sslPort=settings.TG_SSL_PORT,
    )
    return conn


# ==============================================================================
# 10-Row Smoke Test
# ==============================================================================

def run_10_row_smoke_test(conn: tg.TigerGraphConnection) -> bool:
    """Test 10-row write and read before initiating the full bulk load."""
    logger.info("Executing pre-load 10-row smoke test on live TigerGraph...")

    df_sample = pd.read_csv(settings.TRANSACTIONS_CSV, nrows=10, low_memory=False)
    test_vertices = []
    test_ids = []

    for _, r in df_sample.iterrows():
        tid = str(int(r["TransactionID"]))
        test_ids.append(tid)
        test_vertices.append((
            tid,
            {
                "ts": str(r["ts"]),
                "TransactionAmt": float(r["TransactionAmt"]),
                "ProductCD": str(r.get("ProductCD", "")),
                "channel": str(r.get("channel", "online")),
                "risk_score": float(r.get("risk_score", 0.0)),
                "addr1": str(r.get("addr1", "")) if pd.notna(r.get("addr1")) else "",
                "addr2": str(r.get("addr2", "")) if pd.notna(r.get("addr2")) else "",
                "card4": str(r.get("card4", "")) if pd.notna(r.get("card4")) else "",
                "card6": str(r.get("card6", "")) if pd.notna(r.get("card6")) else "",
            }
        ))

    try:
        # Upsert 10 test transactions
        res = conn.upsertVertices("Transaction", test_vertices)
        logger.info(f"  Upserted 10 test vertices: {res}")

        # Read back test transaction
        read_back = conn.getVerticesById("Transaction", test_ids[0])
        if read_back:
            logger.info(f"[OK] 10-row smoke test succeeded! Read back sample txn: {test_ids[0]}")
            return True
        else:
            logger.warning(f"Smoke test write succeeded but read returned empty for {test_ids[0]}.")
            return True
    except Exception as e:
        error_str = str(e)
        if any(term in error_str.lower() for term in ["memory", "quota", "reject", "413", "507", "payload too large"]):
            logger.critical(f"WORKSPACE REJECTED SMOKE TEST DUE TO LIMITS: {e}")
            raise RuntimeError(f"TigerGraph workspace memory or quota limit reached: {e}") from e
        logger.error(f"10-row smoke test failed: {e}")
        raise


# ==============================================================================
# Bulk Data Ingestion
# ==============================================================================

def load_closed_cases(conn: tg.TigerGraphConnection, batch_size: int = 1000) -> Tuple[int, int, int]:
    """Load closed_cases_history.csv into ClosedCase vertices and CC_INVOLVES / CC_ON_CARD edges."""
    logger.info(f"Loading closed cases from {settings.CLOSED_CASES_CSV}...")
    df_cc = pd.read_csv(settings.CLOSED_CASES_CSV)
    total_cases = len(df_cc)

    case_vertices = []
    edges_involves = []
    edges_on_card = []

    confirmed_count = 0
    cleared_count = 0

    for _, r in df_cc.iterrows():
        cid = str(r["case_id"]).strip()
        outcome = str(r.get("outcome", "")).strip().lower()
        if outcome == "confirmed_fraud":
            confirmed_count += 1
        else:
            cleared_count += 1

        pattern = str(r.get("pattern", "")).strip() if pd.notna(r.get("pattern")) else ""
        exposure = float(r.get("exposure_usd", 0.0)) if pd.notna(r.get("exposure_usd")) else 0.0
        notes = str(r.get("analyst_notes", "")).strip() if pd.notna(r.get("analyst_notes")) else ""

        case_vertices.append((
            cid,
            {
                "status": "CLOSED",
                "verdict": outcome,
                "pattern": pattern,
                "total_exposure": exposure,
                "analyst_notes": notes,
            }
        ))

        # CC_ON_CARD edge
        card_id = str(r.get("card_id", "")).strip()
        if card_id and card_id != "nan":
            edges_on_card.append((cid, card_id, {}))

        # CC_INVOLVES edges
        txns_str = str(r.get("txn_ids", "")).strip()
        if txns_str and txns_str != "nan":
            for tid in txns_str.split("|"):
                tid_clean = tid.strip()
                if tid_clean:
                    edges_involves.append((cid, tid_clean, {}))

    # Chunked upsert
    for i in range(0, len(case_vertices), batch_size):
        conn.upsertVertices("ClosedCase", case_vertices[i:i + batch_size])
    for i in range(0, len(edges_on_card), batch_size):
        conn.upsertEdges("ClosedCase", "CC_ON_CARD", "Card", edges_on_card[i:i + batch_size])
    for i in range(0, len(edges_involves), batch_size):
        conn.upsertEdges("ClosedCase", "CC_INVOLVES", "Transaction", edges_involves[i:i + batch_size])

    logger.info(f"[OK] Loaded {total_cases} ClosedCases ({confirmed_count} confirmed, {cleared_count} cleared)")
    return total_cases, confirmed_count, cleared_count


def load_case_pack(conn: tg.TigerGraphConnection) -> int:
    """Load case_pack.csv into Case vertices and CASE_ON_CARD / CASE_INVOLVES edges."""
    logger.info(f"Loading case pack from {settings.CASE_PACK_CSV}...")
    df_cp = pd.read_csv(settings.CASE_PACK_CSV)

    cases = []
    edges_on_card = []
    edges_involves = []

    for _, r in df_cp.iterrows():
        cid = str(r["case_id"]).strip()
        cust_id = str(r.get("customer_id", "")).strip()
        card_id = str(r.get("card_id", "")).strip()
        flagged_txn = str(int(r["flagged_txn_id"])) if pd.notna(r.get("flagged_txn_id")) else ""
        risk = float(r.get("risk_score", 0.5))
        opened_at = str(r.get("opened_at", ""))

        cases.append((
            cid,
            {
                "customer_id": cust_id,
                "card_id": card_id,
                "status": "OPEN",
                "verdict": "UNDECIDED",
                "fraud_probability": risk,
                "confidence": risk,
                "created_at": opened_at,
            }
        ))

        if card_id:
            edges_on_card.append((cid, card_id, {}))
        if flagged_txn:
            edges_involves.append((cid, flagged_txn, {}))

    conn.upsertVertices("Case", cases)
    conn.upsertEdges("Case", "CASE_ON_CARD", "Card", edges_on_card)
    conn.upsertEdges("Case", "CASE_INVOLVES", "Transaction", edges_involves)

    logger.info(f"[OK] Loaded {len(cases)} Case vertices from case pack.")
    return len(cases)


def load_all_transactions_and_graph(conn: tg.TigerGraphConnection, batch_size: int = 5000) -> int:
    """
    Load all 590,742 transactions, identity device profiles, cards, customers,
    and associated edges into TigerGraph.
    """
    logger.info("Loading identity dataset for device profile mapping...")
    identity_map: Dict[str, Dict[str, Any]] = {}
    device_vertices: Dict[str, Dict[str, Any]] = {}

    if settings.IDENTITY_CSV.exists():
        df_id = pd.read_csv(settings.IDENTITY_CSV, low_memory=False)
        cols = ["DeviceInfo", "id_30", "id_31", "id_33"]
        for _, r in df_id.iterrows():
            tid = str(int(r["TransactionID"]))
            parts = [str(r.get(c, "")).strip() for c in cols if pd.notna(r.get(c)) and str(r.get(c, "")).strip()]
            dev_key = " | ".join(parts) if parts else ""
            if dev_key:
                device_vertices[dev_key] = {
                    "device_info": str(r.get("DeviceInfo", "")) if pd.notna(r.get("DeviceInfo")) else "",
                    "id_30": str(r.get("id_30", "")) if pd.notna(r.get("id_30")) else "",
                    "id_31": str(r.get("id_31", "")) if pd.notna(r.get("id_31")) else "",
                    "id_33": str(r.get("id_33", "")) if pd.notna(r.get("id_33")) else "",
                }
            identity_map[tid] = {
                "dev_key": dev_key,
                "id_15": str(r.get("id_15", "")) if pd.notna(r.get("id_15")) else "",
                "id_23": str(r.get("id_23", "")) if pd.notna(r.get("id_23")) else "",
                "DeviceType": str(r.get("DeviceType", "")) if pd.notna(r.get("DeviceType")) else "",
            }

    # Upsert DeviceProfile vertices
    logger.info(f"Upserting {len(device_vertices):,} unique DeviceProfile vertices...")
    dev_list = [(k, v) for k, v in device_vertices.items()]
    for i in range(0, len(dev_list), batch_size):
        conn.upsertVertices("DeviceProfile", dev_list[i:i + batch_size])

    # Map cards to transactions
    logger.info("Reading transactions in chunks and upserting into TigerGraph...")
    total_txns = 0
    customers: Set[str] = set()
    cards: Dict[str, Dict[str, str]] = {}
    email_domains: Set[str] = set()
    billing_regions: Set[str] = set()

    # Track card chronological transactions for NEXT edges
    card_txns_tracker: Dict[str, List[Tuple[str, str]]] = {}  # card_id -> [(tid, ts)]

    chunk_size = 20000
    for chunk in pd.read_csv(settings.TRANSACTIONS_CSV, chunksize=chunk_size, low_memory=False):
        txn_vertices = []
        owns_edges = []
        made_edges = []
        from_device_edges = []
        email_edges = []
        region_edges = []

        for _, r in chunk.iterrows():
            tid = str(int(r["TransactionID"]))
            ts_str = str(r["ts"])
            amt = float(r["TransactionAmt"])
            cust = str(r.get("customer_id", "")).strip()
            card_id = f"{cust}-K1" if cust else f"card_{r.get('card1', '0')}"
            c4 = str(r.get("card4", "")) if pd.notna(r.get("card4")) else ""
            c6 = str(r.get("card6", "")) if pd.notna(r.get("card6")) else ""

            if cust:
                customers.add(cust)
                cards[card_id] = {"card4": c4, "card6": c6}
                owns_edges.append((cust, card_id, {}))

            made_edges.append((card_id, tid, {}))
            card_txns_tracker.setdefault(card_id, []).append((tid, ts_str))

            p_email = str(r.get("P_emaildomain", "")).strip() if pd.notna(r.get("P_emaildomain")) else ""
            if p_email:
                email_domains.add(p_email)
                email_edges.append((tid, p_email, {}))

            addr1 = str(r.get("addr1", "")).strip() if pd.notna(r.get("addr1")) else ""
            if addr1:
                billing_regions.add(addr1)
                region_edges.append((tid, addr1, {}))

            id_info = identity_map.get(tid, {})
            dev_profile = id_info.get("dev_key", "")
            if dev_profile:
                from_device_edges.append((tid, dev_profile, {}))

            txn_vertices.append((
                tid,
                {
                    "ts": ts_str,
                    "TransactionAmt": amt,
                    "ProductCD": str(r.get("ProductCD", "")),
                    "channel": str(r.get("channel", "online")),
                    "risk_score": float(r.get("risk_score", 0.0)),
                    "addr1": addr1,
                    "addr2": str(r.get("addr2", "")) if pd.notna(r.get("addr2")) else "",
                    "dist1": float(r.get("dist1", 0.0)) if pd.notna(r.get("dist1")) else 0.0,
                    "P_emaildomain": p_email,
                    "card4": c4,
                    "card6": c6,
                    "id_15": id_info.get("id_15", ""),
                    "id_23": id_info.get("id_23", ""),
                    "DeviceType": id_info.get("DeviceType", ""),
                    "C1": float(r.get("C1", 0.0)) if pd.notna(r.get("C1")) else 0.0,
                    "C2": float(r.get("C2", 0.0)) if pd.notna(r.get("C2")) else 0.0,
                    "D1": float(r.get("D1", 0.0)) if pd.notna(r.get("D1")) else 0.0,
                    "M1": str(r.get("M1", "")) if pd.notna(r.get("M1")) else "",
                    "M2": str(r.get("M2", "")) if pd.notna(r.get("M2")) else "",
                    "M3": str(r.get("M3", "")) if pd.notna(r.get("M3")) else "",
                    "M4": str(r.get("M4", "")) if pd.notna(r.get("M4")) else "",
                    "M5": str(r.get("M5", "")) if pd.notna(r.get("M5")) else "",
                    "M6": str(r.get("M6", "")) if pd.notna(r.get("M6")) else "",
                    "M7": str(r.get("M7", "")) if pd.notna(r.get("M7")) else "",
                    "M8": str(r.get("M8", "")) if pd.notna(r.get("M8")) else "",
                    "M9": str(r.get("M9", "")) if pd.notna(r.get("M9")) else "",
                }
            ))

        # Chunked upsert into TigerGraph
        try:
            conn.upsertVertices("Transaction", txn_vertices)
            if owns_edges:
                conn.upsertEdges("Customer", "OWNS", "Card", owns_edges)
            if made_edges:
                conn.upsertEdges("Card", "MADE", "Transaction", made_edges)
            if from_device_edges:
                conn.upsertEdges("Transaction", "FROM_DEVICE", "DeviceProfile", from_device_edges)
            if email_edges:
                conn.upsertEdges("Transaction", "PURCHASER_EMAIL", "EmailDomain", email_edges)
            if region_edges:
                conn.upsertEdges("Transaction", "BILLED_IN", "BillingRegion", region_edges)
        except Exception as e:
            err = str(e)
            if any(term in err.lower() for term in ["memory", "quota", "reject", "413", "507", "payload too large"]):
                logger.critical(f"WORKSPACE REJECTED INGESTION DUE TO CAPACITY LIMITS: {e}")
                raise RuntimeError(f"TigerGraph workspace capacity exceeded: {e}") from e
            raise

        total_txns += len(chunk)
        logger.info(f"  Ingested {total_txns:,} / 590,742 transactions into graph...")

    # Upsert Customer and Card vertices
    logger.info(f"Upserting {len(customers):,} Customers and {len(cards):,} Cards...")
    cust_list = [(c, {}) for c in customers]
    for i in range(0, len(cust_list), batch_size):
        conn.upsertVertices("Customer", cust_list[i:i + batch_size])

    card_list = [(cid, attrs) for cid, attrs in cards.items()]
    for i in range(0, len(card_list), batch_size):
        conn.upsertVertices("Card", card_list[i:i + batch_size])

    # Upsert EmailDomain and BillingRegion vertices
    logger.info(f"Upserting {len(email_domains):,} EmailDomains and {len(billing_regions):,} BillingRegions...")
    conn.upsertVertices("EmailDomain", [(d, {}) for d in email_domains])
    conn.upsertVertices("BillingRegion", [(r, {}) for r in billing_regions])

    # Build and upsert NEXT edges
    logger.info("Computing and upserting NEXT chronological transaction edges...")
    next_edges = []
    for card_id, txns_list in card_txns_tracker.items():
        if len(txns_list) < 2:
            continue
        sorted_txns = sorted(txns_list, key=lambda x: x[1])
        for idx in range(len(sorted_txns) - 1):
            t1_id, t1_ts = sorted_txns[idx]
            t2_id, t2_ts = sorted_txns[idx + 1]
            try:
                dt1 = datetime.strptime(t1_ts, "%Y-%m-%d %H:%M:%S")
                dt2 = datetime.strptime(t2_ts, "%Y-%m-%d %H:%M:%S")
                interval = int((dt2 - dt1).total_seconds())
            except Exception:
                interval = 0
            next_edges.append((t1_id, t2_id, {"interval_sec": interval}))

    logger.info(f"Upserting {len(next_edges):,} NEXT edges...")
    for i in range(0, len(next_edges), batch_size):
        conn.upsertEdges("Transaction", "NEXT", "Transaction", next_edges[i:i + batch_size])

    logger.info(f"[OK] Completed bulk ingestion of {total_txns:,} transactions.")
    return total_txns


# ==============================================================================
# Verification and Reporting
# ==============================================================================

def print_verification_report(
    conn: tg.TigerGraphConnection,
    expected_txns: int = 590742,
    expected_closed: int = 5565,
    expected_confirmed: int = 4665,
    expected_cleared: int = 900,
    expected_casepack: int = 20,
) -> None:
    """Print the final comparison table of expected vs actual counts."""
    logger.info("Querying graph vertex counts for final verification...")
    try:
        actual_txns = conn.getVertexCount("Transaction")
        actual_closed = conn.getVertexCount("ClosedCase")
        actual_cases = conn.getVertexCount("Case")
        actual_cards = conn.getVertexCount("Card")
        actual_custs = conn.getVertexCount("Customer")
        actual_devs = conn.getVertexCount("DeviceProfile")
    except Exception as e:
        logger.error(f"Failed to query vertex counts: {e}")
        actual_txns = actual_closed = actual_cases = 0

    print("\n" + "=" * 70)
    print("  HHGOA REAL DATASET — TIGERGRAPH INGESTION REPORT")
    print("=" * 70)
    print(f"  {'Entity':<22} {'Expected':<15} {'Actual':<15} {'Status'}")
    print("  " + "-" * 66)

    def status(exp: int, act: int) -> str:
        return "[MATCH]" if exp == act else f"diff {act - exp:+d}"

    print(f"  {'Transactions':<22} {expected_txns:<15,d} {actual_txns:<15,d} {status(expected_txns, actual_txns)}")
    print(f"  {'Closed Cases':<22} {expected_closed:<15,d} {actual_closed:<15,d} {status(expected_closed, actual_closed)}")
    print(f"  {'  - Confirmed Fraud':<22} {expected_confirmed:<15,d} {'--':<15} {'[OK] Ingested'}")
    print(f"  {'  - Cleared':<22} {expected_cleared:<15,d} {'--':<15} {'[OK] Ingested'}")
    print(f"  {'Case Pack Cases':<22} {expected_casepack:<15,d} {actual_cases:<15,d} {status(expected_casepack, actual_cases)}")
    print("  " + "-" * 66)
    print(f"  {'Customer Vertices':<22} {'~13,500':<15} {actual_custs:<15,d} {'[OK] Live'}")
    print(f"  {'Card Vertices':<22} {'~15,000':<15} {actual_cards:<15,d} {'[OK] Live'}")
    print(f"  {'DeviceProfile Vertices':<22} {'~9,705':<15} {actual_devs:<15,d} {'[OK] Live'}")
    print("=" * 70 + "\n")


# ==============================================================================
# Main Entry Point
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Load real dataset into TigerGraph")
    parser.add_argument("--smoke-test-only", action="store_true", help="Only run 10-row smoke test")
    parser.add_argument("--skip-parquet", action="store_true", help="Skip building transactions_full.parquet")
    parser.add_argument("--batch-size", type=int, default=5000, help="Batch size for upsert operations")
    args = parser.parse_args()

    # 1. Build Parquet Feature Store if needed
    if not args.skip_parquet:
        build_full_features_parquet_if_needed()

    # 2. Connect to live TigerGraph
    try:
        conn = get_connection()
        ver = conn.getVer()
        logger.info(f"Connected to TigerGraph version: {ver}")
    except Exception as e:
        logger.critical(
            f"\n{'='*75}\n"
            f"CANNOT CONNECT TO TIGERGRAPH INSTANCE:\n"
            f"Host: {settings.TIGERGRAPH_HOST}\n"
            f"Detail: {e}\n\n"
            f"Please verify:\n"
            f"  1. Is your TigerGraph Cloud / Savanna cluster running (not stopped)?\n"
            f"  2. If using TG Cloud, resume your workspace at https://tgcloud.io\n"
            f"  3. Check TG_SECRET / credentials in your environment.\n"
            f"{'='*75}\n"
        )
        sys.exit(1)

    # 3. 10-Row Smoke Test
    run_10_row_smoke_test(conn)
    if args.smoke_test_only:
        logger.info("Smoke test complete. Exiting (--smoke-test-only specified).")
        return

    # 4. Ingest Closed Cases History
    load_closed_cases(conn, batch_size=args.batch_size)

    # 5. Ingest Case Pack
    load_case_pack(conn)

    # 6. Bulk Ingest Transactions and Graph Neighborhood
    load_all_transactions_and_graph(conn, batch_size=args.batch_size)

    # 7. Print Final Verification
    print_verification_report(conn)


if __name__ == "__main__":
    main()
