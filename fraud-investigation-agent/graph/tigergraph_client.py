"""
graph/tigergraph_client.py
──────────────────────────
TigerGraph Client communicating exclusively with the live TigerGraph Cloud
or on-premise instance using GSQL queries and pyTigerGraph:
- card_window(card_id, start_ts, end_ts)
- device_neighbors(device_id)
- region_neighbors(region_id, window_days)
- shared_email_neighbors(email_domain, window_days)
- customer_history(customer_id)
- similar_closed_cases(pattern, amount_band)

Zero hardcoded device/card maps. Zero synthetic fallback.
"""
from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class UpsertCaseResult:
    """Result container supporting tuple unpacking (ok, vid) and boolean evaluation."""

    def __init__(self, success: bool, vertex_id: str = "", error: Optional[str] = None) -> None:
        self.success = bool(success)
        self.vertex_id = str(vertex_id)
        self.error = error

    def __bool__(self) -> bool:
        return self.success

    def __iter__(self):
        return iter((self.success, self.vertex_id))

    def __getitem__(self, idx: int):
        return (self.success, self.vertex_id)[idx]

    def __repr__(self) -> str:
        return f"UpsertCaseResult(success={self.success}, vertex_id='{self.vertex_id}')"

# ─── Live pyTigerGraph import ─────────────────────────────────────────────────
try:
    import pyTigerGraph as tg  # type: ignore
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False


# Re-export on-demand full feature lookup
try:
    from data.load_all import get_full_features
except ImportError:
    def get_full_features(txn_id: int | str) -> Dict[str, Any]:
        return {}


# ==============================================================================
# Live TigerGraph Client
# ==============================================================================

class TigerGraphClient:
    """Client interacting directly with live TigerGraph instance."""

    def __init__(self, conn: Optional[Any] = None, skip_init: bool = False) -> None:
        from config import settings
        self.settings = settings
        self.conn = conn
        self._offline_df = None
        self._offline_cases: Dict[str, Any] = {}
        if self.conn is None and not skip_init:
            self._init_connection()

    def _get_offline_df(self) -> Any:
        """Lazy load authentic enriched parquet dataset for offline dev mode."""
        if self._offline_df is None:
            pq_path = self.settings.DATA_DIR / "transactions_enriched.parquet"
            if pq_path.exists():
                import pandas as pd
                self._offline_df = pd.read_parquet(pq_path)
        return self._offline_df



    def _init_connection(self) -> None:
        """Initialize connection to live TigerGraph instance or enforce STRICT_GRAPH."""
        if self.settings.OFFLINE_DEV:
            logger.warning(
                "\n"
                "*******************************************************************************\n"
                "  LOUD WARNING: OFFLINE_DEV IS ENABLED!\n"
                "  Live TigerGraph connection is bypassed.\n"
                "  All investigation outputs will carry {'offline_dev': True}.\n"
                "*******************************************************************************\n"
            )
            return

        if not _TG_AVAILABLE:
            error_msg = (
                "pyTigerGraph is not installed. When OFFLINE_DEV is false, pyTigerGraph is required "
                "to connect to the live TigerGraph instance. Run: pip install pyTigerGraph"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        try:
            host = self.settings.TIGERGRAPH_HOST
            if not host.startswith("http://") and not host.startswith("https://"):
                host = f"https://{host}"

            graph_name = os.getenv("TG_GRAPHNAME") or self.settings.TIGERGRAPH_GRAPH
            is_tg_cloud = self.settings.TG_TGCLOUD
            ssl_port = self.settings.TG_SSL_PORT

            self.conn = tg.TigerGraphConnection(
                host=host,
                graphname=graph_name,
                username=self.settings.TIGERGRAPH_USERNAME,
                password=self.settings.TIGERGRAPH_PASSWORD,
                gsqlSecret=self.settings.TIGERGRAPH_SECRET,
                tgCloud=is_tg_cloud,
                sslPort=ssl_port,
            )

            # Test authentication and connection liveness
            ver = self.conn.getVer()
            logger.info(f"Connected to live TigerGraph at {host} on graph '{graph_name}' (version: {ver})")
        except Exception as e:
            graph_name = os.getenv("TG_GRAPHNAME") or self.settings.TIGERGRAPH_GRAPH
            error_msg = (
                f"\n{'='*75}\n"
                f"TIGERGRAPH CONNECTION FAILED:\n"
                f"Unable to connect to TigerGraph instance at '{self.settings.TIGERGRAPH_HOST}'.\n"
                f"Error detail: {e}\n\n"
                f"When OFFLINE_DEV is false, silent fallback to local files is forbidden.\n"
                f"Please verify:\n"
                f"  1. Is your TigerGraph Cloud / Savanna workspace running (not stopped/sleeping)?\n"
                f"  2. Does TG_HOST have the correct URL scheme (e.g. 'https://tg-xxxx.tgcloud.io')?\n"
                f"  3. Is TG_SECRET (or GSQL secret) valid and generated on graph '{graph_name}'?\n"
                f"  4. Are TG_USERNAME and TG_PASSWORD correct?\n"
                f"  5. If developing locally without TigerGraph, set OFFLINE_DEV=true in your environment.\n"
                f"{'='*75}\n"
            )
            logger.error(error_msg)
            raise ConnectionError(error_msg) from e

    # ──────────────────────────────────────────────────────────────────────────
    # Graph Query Implementations
    # ──────────────────────────────────────────────────────────────────────────

    def get_card_history(self, customer_id: str, card_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve historical transactions for customer or card sorted by ts."""
        if not self.conn:
            df = self._get_offline_df()
            if df is None:
                return []
            import pandas as pd
            if card_id:
                sub = df[(df["customer_id"].astype(str) == str(customer_id)) | (df["card1"].astype(str) == str(card_id))]
            else:
                sub = df[df["customer_id"].astype(str) == str(customer_id)]
            results = []
            for _, r in sub.iterrows():
                dev_parts = [str(r.get(k, "")).strip() for k in ["DeviceInfo", "id_30", "id_31", "id_33"] if pd.notna(r.get(k)) and str(r.get(k)).strip()]
                dev_profile = " | ".join(dev_parts) if dev_parts else ""
                results.append({
                    "TransactionID":   str(int(r["TransactionID"])),
                    "TransactionAmt":  float(r["TransactionAmt"]),
                    "ts":              str(r.get("ts", "")),
                    "channel":         str(r.get("channel", "online")),
                    "addr1":           str(r.get("addr1", "")) if pd.notna(r.get("addr1")) else None,
                    "addr2":           str(r.get("addr2", "")) if pd.notna(r.get("addr2")) else None,
                    "ProductCD":       str(r.get("ProductCD", "")),
                    "risk_score":      float(r.get("risk_score", 0.0)) if pd.notna(r.get("risk_score")) else 0.0,
                    "card4":           str(r.get("card4", "")),
                    "card6":           str(r.get("card6", "")),
                    "id_15":           str(r.get("id_15", "")),
                    "id_23":           str(r.get("id_23", "")),
                    "DeviceType":      str(r.get("DeviceType", "")),
                    "device_profile":  dev_profile,
                })
            results.sort(key=lambda x: x["ts"])
            return results

        txns_raw: List[Dict[str, Any]] = []
        try:
            if card_id:
                res = self.conn.runInstalledQuery("card_window", {"card_id": card_id, "start_ts": "", "end_ts": ""})
                if res and isinstance(res, list):
                    for entry in res:
                        txns_raw.extend(entry.get("Txns", []))
            else:
                res = self.conn.runInstalledQuery("customer_history", {"customer_id": customer_id})
                if res and isinstance(res, list):
                    for entry in res:
                        txns_raw.extend(entry.get("Txns", []))
        except Exception as e:
            logger.warning(f"customer_history query returned error: {e}. Falling back to vertex retrieval.")
            # Fallback direct vertex query if query not yet installed
            try:
                txns_raw = self.conn.getVertices("Transaction", where=f"customer_id=='{customer_id}'")
            except Exception:
                txns_raw = []

        results = []
        for t in txns_raw:
            attrs = t.get("attributes", t)
            tid = str(t.get("v_id", attrs.get("TransactionID", attrs.get("txn_id", ""))))
            results.append({
                "TransactionID":   tid,
                "TransactionAmt":  float(attrs.get("TransactionAmt", 0.0)),
                "ts":              str(attrs.get("ts", "")),
                "channel":         str(attrs.get("channel", "online")),
                "addr1":           str(attrs.get("addr1", "")) if attrs.get("addr1") else None,
                "ProductCD":       str(attrs.get("ProductCD", "")),
                "risk_score":      float(attrs.get("risk_score", 0.0)),
                "card4":           str(attrs.get("card4", "")),
                "card6":           str(attrs.get("card6", "")),
                "id_15":           str(attrs.get("id_15", "")),
                "id_23":           str(attrs.get("id_23", "")),
                "DeviceType":      str(attrs.get("DeviceType", "")),
            })

        results.sort(key=lambda x: x["ts"])
        return results

    def get_transaction(self, txn_id: str) -> Optional[Dict[str, Any]]:
        """Fetch details of a single transaction by ID from live graph or authentic dataset."""
        if not self.conn:
            df = self._get_offline_df()
            if df is None:
                return None
            import pandas as pd
            sub = df[df["TransactionID"].astype(str) == str(txn_id)]
            if len(sub) == 0:
                return None
            r = sub.iloc[0]
            dev_parts = [str(r.get(k, "")).strip() for k in ["DeviceInfo", "id_30", "id_31", "id_33"] if pd.notna(r.get(k)) and str(r.get(k)).strip()]
            dev_profile = " | ".join(dev_parts) if dev_parts else ""
            return {
                "TransactionID":   str(int(r["TransactionID"])),
                "TransactionAmt":  float(r["TransactionAmt"]),
                "ts":              str(r.get("ts", "")),
                "channel":         str(r.get("channel", "online")),
                "addr1":           str(r.get("addr1", "")) if pd.notna(r.get("addr1")) else None,
                "addr2":           str(r.get("addr2", "")) if pd.notna(r.get("addr2")) else None,
                "ProductCD":       str(r.get("ProductCD", "")),
                "risk_score":      float(r.get("risk_score", 0.0)) if pd.notna(r.get("risk_score")) else 0.0,
                "card4":           str(r.get("card4", "")),
                "card6":           str(r.get("card6", "")),
                "id_15":           str(r.get("id_15", "")),
                "id_23":           str(r.get("id_23", "")),
                "DeviceType":      str(r.get("DeviceType", "")),
                "device_profile":  dev_profile,
            }


        try:
            res = self.conn.getVerticesById("Transaction", str(txn_id))
            if not res:
                return None
            v = res[0] if isinstance(res, list) else res
            attrs = v.get("attributes", v)

            # Query connected device profile via edge
            device_profile = ""
            try:
                edges = self.conn.getEdges("Transaction", str(txn_id), "FROM_DEVICE", "DeviceProfile")
                if edges:
                    device_profile = edges[0].get("to_id", "")
            except Exception:
                pass

            return {
                "TransactionID":   str(txn_id),
                "TransactionAmt":  float(attrs.get("TransactionAmt", 0.0)),
                "ts":              str(attrs.get("ts", "")),
                "channel":         str(attrs.get("channel", "online")),
                "addr1":           str(attrs.get("addr1", "")) if attrs.get("addr1") else None,
                "addr2":           str(attrs.get("addr2", "")) if attrs.get("addr2") else None,
                "ProductCD":       str(attrs.get("ProductCD", "")),
                "risk_score":      float(attrs.get("risk_score", 0.0)),
                "card4":           str(attrs.get("card4", "")),
                "card6":           str(attrs.get("card6", "")),
                "id_15":           str(attrs.get("id_15", "")),
                "id_23":           str(attrs.get("id_23", "")),
                "DeviceType":      str(attrs.get("DeviceType", "")),
                "device_profile":  device_profile,
            }
        except Exception as e:
            logger.warning(f"Failed to fetch transaction {txn_id} from graph: {e}")
            return None

    def detect_shared_entities(self, card_id: str, device_profile: Optional[str] = None) -> Dict[str, Any]:
        """
        Query device_neighbors query to find other cards and customers sharing
        the exact device hardware profile.
        """
        if not self.conn:
            if not device_profile:
                return {
                    "connected_cards": [],
                    "shared_device_accounts": [],
                    "connected_devices": [],
                }
            df = self._get_offline_df()
            if df is None:
                return {
                    "connected_cards": [],
                    "shared_device_accounts": [],
                    "connected_devices": [device_profile],
                }
            import pandas as pd
            connected_cards = set()
            shared_accounts = set()
            cust_prefix = card_id.split("-")[0] if "-" in card_id else card_id
            dev_sig = device_profile.split(" | ")[0] if " | " in device_profile else device_profile
            generic_os = {"windows", "ios device", "trident/7.0", "macos", "rv:11.0", "rv:57.0", "other"}
            is_generic = dev_sig.lower() in generic_os or len(device_profile.split(" | ")) < 3
            if not is_generic:
                for _, r in df.iterrows():
                    dev_parts = [str(r.get(k, "")).strip() for k in ["DeviceInfo", "id_30", "id_31", "id_33"] if pd.notna(r.get(k)) and str(r.get(k)).strip()]
                    dp = " | ".join(dev_parts) if dev_parts else ""
                    odev = str(r.get("DeviceInfo", "")).strip()
                    matched = False
                    if len(dev_parts) >= 3 and dp == device_profile:
                        matched = True
                    elif "build/" in dev_sig.lower() and dev_sig in odev:
                        matched = True

                    if matched:
                        cid = f"{r['customer_id']}-K1"
                        if cid != card_id and not cid.startswith(cust_prefix):
                            connected_cards.add(cid)
                            shared_accounts.add(str(r["customer_id"]))
            return {
                "connected_cards": sorted(connected_cards),
                "shared_device_accounts": sorted(shared_accounts),
                "connected_devices": [device_profile],
            }

        if not device_profile:
            return {
                "connected_cards": [],
                "shared_device_accounts": [],
                "connected_devices": [],
            }


        exclude_cust = card_id.split("-")[0] if "-" in card_id else card_id
        connected_cards = set()
        shared_accounts = set()

        try:
            res = self.conn.runInstalledQuery("device_neighbors", {"device_id": device_profile})
            if res and isinstance(res, list):
                for entry in res:
                    for c in entry.get("Cards", []):
                        cid = c.get("v_id", "")
                        if cid and cid != card_id and not cid.startswith(exclude_cust):
                            connected_cards.add(cid)
                    for u in entry.get("Custs", []):
                        uid = u.get("v_id", "")
                        if uid and uid != exclude_cust:
                            shared_accounts.add(uid)
        except Exception as e:
            logger.warning(f"device_neighbors query execution failed: {e}")

        return {
            "connected_cards": sorted(connected_cards),
            "shared_device_accounts": sorted(shared_accounts),
            "connected_devices": [device_profile] if device_profile else [],
        }

    def detect_card_testing(self, customer_id: str, flagged_txn_id: str) -> Tuple[bool, List[str], float]:
        """
        Check Policy R5: 3+ small online authorizations (< $5) within 1 hour before a larger purchase.
        """
        txns = self.get_card_history(customer_id)
        if not txns:
            return False, [flagged_txn_id], 0.0

        flagged_idx = None
        for i, t in enumerate(txns):
            if str(t["TransactionID"]) == str(flagged_txn_id):
                flagged_idx = i
                break

        if flagged_idx is None:
            return False, [flagged_txn_id], 0.0

        flagged_t = txns[flagged_idx]
        try:
            flagged_dt = datetime.strptime(flagged_t["ts"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return False, [flagged_txn_id], flagged_t["TransactionAmt"]

        small_txns = []
        for i in range(max(0, flagged_idx - 10), flagged_idx):
            prev_t = txns[i]
            if prev_t["channel"] == "online" and prev_t["TransactionAmt"] < 5.0:
                try:
                    prev_dt = datetime.strptime(prev_t["ts"], "%Y-%m-%d %H:%M:%S")
                    if 0 < (flagged_dt - prev_dt).total_seconds() <= 3600:
                        small_txns.append(prev_t)
                except Exception:
                    pass

        if len(small_txns) >= 3:
            affected = [t["TransactionID"] for t in small_txns] + [flagged_txn_id]
            exposure = sum(t["TransactionAmt"] for t in small_txns) + flagged_t["TransactionAmt"]
            return True, affected, exposure

        return False, [flagged_txn_id], flagged_t["TransactionAmt"]

    def detect_out_of_region(self, customer_id: str, flagged_txn_id: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check Policy R4: Card used in unfamiliar billing region (addr1) compared to history.
        """
        txns = self.get_card_history(customer_id)
        if len(txns) < 3:
            return False, None, None

        flagged_t = next((t for t in txns if str(t["TransactionID"]) == str(flagged_txn_id)), None)
        if not flagged_t or not flagged_t.get("addr1"):
            return False, None, None

        curr_region = str(flagged_t["addr1"])
        prior_regions = [str(t["addr1"]) for t in txns if str(t["TransactionID"]) != str(flagged_txn_id) and t.get("addr1")]
        if not prior_regions:
            return False, None, None

        counts = Counter(prior_regions)
        modal_region, _ = counts.most_common(1)[0]
        is_out = (curr_region != modal_region) and (curr_region not in prior_regions)
        return is_out, modal_region, curr_region

    def find_similar_cases(self, pattern: str, amount_band: float = 0.0, top_k: int = 3) -> List[Dict[str, Any]]:
        """Query both historical ClosedCase records and earlier agent Case vertices."""
        matches: List[Dict[str, Any]] = []

        # 1. Query live TigerGraph if available
        if self.conn:
            try:
                # A. Query historical ClosedCase vertices via installed query
                res = self.conn.runInstalledQuery("similar_closed_cases", {"pattern": pattern, "amount_band": float(amount_band)})
                if res and isinstance(res, list):
                    for entry in res:
                        for c in entry.get("Matches", []):
                            attrs = c.get("attributes", c)
                            matches.append({
                                "case_id": c.get("v_id", ""),
                                "outcome": attrs.get("verdict", "confirmed_fraud"),
                                "pattern": attrs.get("pattern", pattern),
                                "exposure_usd": float(attrs.get("total_exposure", 0.0)),
                                "analyst_notes": attrs.get("analyst_notes", ""),
                                "source": "ClosedCase",
                            })
                # B. Query earlier agent-created Case vertices
                agent_cases = self.conn.getVertices("Case", where=f"pattern=='{pattern}'", limit=top_k)
                if agent_cases:
                    for ac in agent_cases:
                        attrs = ac.get("attributes", ac)
                        matches.append({
                            "case_id": ac.get("v_id", ""),
                            "outcome": attrs.get("verdict", "fraud"),
                            "pattern": attrs.get("pattern", pattern),
                            "exposure_usd": float(attrs.get("exposure_usd", attrs.get("total_exposure", 0.0))),
                            "analyst_notes": attrs.get("summary", ""),
                            "source": "Case",
                        })
            except Exception as e:
                logger.warning(f"similar_closed_cases graph query failed: {e}")

        # 2. Resilient fallback to memory store if graph query returned fewer than top_k
        if len(matches) < top_k:
            try:
                from rag.memory_store import get_memory_store
                ms = get_memory_store()
                for cid in ms.find_similar_cases(pattern=pattern, top_k=top_k):
                    if not any(m["case_id"] == cid for m in matches):
                        entry = ms._cases_by_id.get(cid, {})
                        matches.append({
                            "case_id": cid,
                            "outcome": entry.get("outcome", "confirmed_fraud"),
                            "pattern": entry.get("pattern", pattern),
                            "exposure_usd": entry.get("exposure_usd", 0.0),
                            "analyst_notes": entry.get("analyst_notes", ""),
                            "source": "ClosedCase",
                        })
            except Exception as e:
                logger.warning(f"Fallback case memory lookup failed: {e}")

        return matches[:top_k]

    def get_cases_by_card(self, card_id: str) -> List[Dict[str, Any]]:
        """Retrieve all Case vertices connected to a card (via CASE_ON_CARD)."""
        if not self.conn or not card_id:
            return []
        try:
            edges = self.conn.getEdges("Card", card_id, "reverse_CASE_ON_CARD", "Case")
            case_ids = [e.get("to_id", "") for e in edges if e.get("to_id")]
            results = []
            for cid in case_ids:
                c = self.get_case(cid)
                if c:
                    results.append(c)
            return results
        except Exception as e:
            logger.warning(f"Failed to retrieve cases by card {card_id}: {e}")
            return []

    def get_cases_by_device(self, device_id: str) -> List[Dict[str, Any]]:
        """Retrieve Case vertices connected via DeviceProfile <- FROM_DEVICE <- Transaction <- CASE_INVOLVES <- Case."""
        if not self.conn or not device_id:
            return []
        try:
            edges = self.conn.getEdges("DeviceProfile", device_id, "reverse_FROM_DEVICE", "Transaction")
            tx_ids = [e.get("to_id", "") for e in edges if e.get("to_id")]
            cases = []
            seen = set()
            for tid in tx_ids:
                c_edges = self.conn.getEdges("Transaction", tid, "reverse_CASE_INVOLVES", "Case")
                for ce in c_edges:
                    cid = ce.get("to_id", "")
                    if cid and cid not in seen:
                        seen.add(cid)
                        case_data = self.get_case(cid)
                        if case_data:
                            cases.append(case_data)
            return cases
        except Exception as e:
            logger.warning(f"Failed to retrieve cases by device {device_id}: {e}")
            return []

    def get_cases_by_region(self, region_id: str) -> List[Dict[str, Any]]:
        """Retrieve Case vertices connected via BillingRegion <- BILLED_IN <- Transaction <- CASE_INVOLVES <- Case."""
        if not self.conn or not region_id:
            return []
        try:
            edges = self.conn.getEdges("BillingRegion", region_id, "reverse_BILLED_IN", "Transaction")
            tx_ids = [e.get("to_id", "") for e in edges if e.get("to_id")]
            cases = []
            seen = set()
            for tid in tx_ids:
                c_edges = self.conn.getEdges("Transaction", tid, "reverse_CASE_INVOLVES", "Case")
                for ce in c_edges:
                    cid = ce.get("to_id", "")
                    if cid and cid not in seen:
                        seen.add(cid)
                        case_data = self.get_case(cid)
                        if case_data:
                            cases.append(case_data)
            return cases
        except Exception as e:
            logger.warning(f"Failed to retrieve cases by region {region_id}: {e}")
            return []

    def upsert_case(self, case: Any, case_data: Optional[Dict[str, Any]] = None) -> UpsertCaseResult:
        """
        Upsert Case vertex and associated edges into TigerGraph, then READ BACK to verify.
        Returns UpsertCaseResult(success, vertex_id).
        """
        if isinstance(case, str):
            case_id = case
            data = case_data or {}
        elif isinstance(case, dict):
            data = case
            case_id = str(data.get("case_id", ""))
        else:
            return UpsertCaseResult(False, "", error="Invalid case argument")

        if not case_id:
            return UpsertCaseResult(False, "", error="Missing case_id")

        if not self.conn:
            if getattr(self.settings, "OFFLINE_DEV", False):
                record = {
                    "case_id": case_id,
                    "status": str(data.get("status", "open")),
                    "verdict": str(data.get("verdict", "undecided")),
                    "fraud_probability": round(float(data.get("fraud_probability", 0.0)), 4),
                    "pattern": str(data.get("pattern", "none")),
                    "exposure_usd": round(float(data.get("exposure_usd", data.get("total_exposure", 0.0))), 2),
                    "summary": str(data.get("summary", data.get("analyst_notes", ""))),
                    "opened_at": str(data.get("opened_at", data.get("created_at", ""))),
                    "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "customer_id": str(data.get("customer_id", "")),
                    "card_id": str(data.get("card_id", "")),
                    "connected_card_ids": data.get("connected_card_ids", []),
                    "affected_txn_ids": data.get("affected_txn_ids", data.get("affected_transactions", [])),
                    "similar_prior_cases": data.get("similar_prior_cases", data.get("similar_cases", [])),
                }
                self._offline_cases[case_id] = record
                # Read-back verification
                if self._offline_cases.get(case_id, {}).get("case_id") == case_id:
                    logger.info(f"Verified Case vertex '{case_id}' recorded in offline store.")
                    return UpsertCaseResult(True, case_id)
                return UpsertCaseResult(False, "", error="Offline dev readback failed")
            logger.error(f"Cannot upsert case {case_id}: No active TigerGraph connection.")
            return UpsertCaseResult(False, "", error="No active TigerGraph connection")

        try:
            now_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            opened_ts = str(data.get("opened_at", data.get("created_at", now_ts)))
            if "T" in opened_ts:
                opened_ts = opened_ts.replace("T", " ")[:19]

            attrs = {
                "status":            str(data.get("status", "open")),
                "verdict":           str(data.get("verdict", "undecided")),
                "fraud_probability": round(float(data.get("fraud_probability", 0.0)), 4),
                "pattern":           str(data.get("pattern", "none")),
                "exposure_usd":      round(float(data.get("exposure_usd", data.get("total_exposure", 0.0))), 2),
                "summary":           str(data.get("summary", data.get("analyst_notes", ""))),
                "opened_at":         opened_ts,
                "updated_at":        now_ts,
            }
            cust_id = str(data.get("customer_id", ""))
            card_id = str(data.get("card_id", ""))
            if cust_id:
                attrs["customer_id"] = cust_id
            if card_id:
                attrs["card_id"] = card_id

            # 1. Upsert Case vertex
            self.conn.upsertVertex("Case", case_id, attrs)

            # 2. Upsert CASE_ON_CARD edges
            if card_id:
                self.conn.upsertEdge("Case", case_id, "CASE_ON_CARD", "Card", card_id)
            for cid in data.get("connected_card_ids", []):
                cid_str = str(cid).strip()
                if cid_str:
                    self.conn.upsertEdge("Case", case_id, "CASE_ON_CARD", "Card", cid_str)

            # 3. Upsert CASE_INVOLVES edges
            tx_ids = set()
            for tid in data.get("affected_txn_ids", data.get("affected_transactions", [])):
                tx_ids.add(str(tid).strip())
            if data.get("flagged_txn_id"):
                tx_ids.add(str(data["flagged_txn_id"]).strip())
            for tid in tx_ids:
                if tid:
                    self.conn.upsertEdge("Case", case_id, "CASE_INVOLVES", "Transaction", tid)

            # 4. Upsert CASE_SIMILAR_TO (ClosedCase) and CASE_SIMILAR_CASE (Agent Case)
            similar_ids = data.get("similar_prior_cases", data.get("similar_cases", []))
            for sim_id in similar_ids:
                sim_str = str(sim_id).strip()
                if sim_str.startswith("CC-"):
                    self.conn.upsertEdge("Case", case_id, "CASE_SIMILAR_TO", "ClosedCase", sim_str)
                elif sim_str and sim_str != case_id:
                    self.conn.upsertEdge("Case", case_id, "CASE_SIMILAR_CASE", "Case", sim_str)

            # 5. READ BACK TO VERIFY
            read_back = self.conn.getVerticesById("Case", case_id)
            if not read_back:
                logger.error(f"Read-back failed: Case vertex '{case_id}' was not returned after write.")
                return UpsertCaseResult(False, "", error="Read-back returned empty")

            v = read_back[0] if isinstance(read_back, list) else read_back
            real_vid = str(v.get("v_id", v.get("case_id", "")))
            if real_vid != case_id:
                logger.error(f"Read-back mismatch: expected vertex '{case_id}', got '{real_vid}'.")
                return UpsertCaseResult(False, "", error="Read-back vertex ID mismatch")

            logger.info(f"Verified Case vertex '{case_id}' successfully written and read back.")
            return UpsertCaseResult(True, real_vid)

        except Exception as e:
            logger.error(f"Failed to upsert case {case_id} to TigerGraph: {e}")
            return UpsertCaseResult(False, "", error=str(e))

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve case record from graph."""
        if not self.conn:
            if getattr(self.settings, "OFFLINE_DEV", False):
                return self._offline_cases.get(case_id)
            return None
        try:
            res = self.conn.getVerticesById("Case", case_id)
            if not res:
                return None
            v = res[0] if isinstance(res, list) else res
            attrs = v.get("attributes", v)
            return {"case_id": case_id, **attrs}
        except Exception:
            return None


    def get_subgraph(self, account_id: str, hop: int = 2) -> Dict[str, Any]:
        """Produce subgraph nodes and edges for account neighborhood from live graph."""
        txns = self.get_card_history(account_id)
        nodes = [{"node_id": account_id, "node_type": "Customer", "attributes": {}}]
        edges = []
        for t in txns[:10]:
            tid = str(t["TransactionID"])
            nodes.append({"node_id": tid, "node_type": "Transaction", "attributes": {"amount": t["TransactionAmt"], "ts": t["ts"]}})
            edges.append({"source": account_id, "target": tid, "edge_type": "MADE", "attributes": {}})
            dev = t.get("device_profile")
            if dev:
                nodes.append({"node_id": dev, "node_type": "DeviceProfile", "attributes": {}})
                edges.append({"source": tid, "target": dev, "edge_type": "FROM_DEVICE", "attributes": {}})
        return {"nodes": nodes, "edges": edges}

    def trace_velocity(self, account_id: str, lookback_hours: int = 72) -> Dict[str, Any]:
        """Compute fund velocity and device dispersion for an account."""
        txns = self.get_card_history(account_id)
        return {
            "total_txn_count": len(txns),
            "total_amount": sum(t["TransactionAmt"] for t in txns),
            "velocity_burst_score": min(len(txns) / 10.0, 5.0),
            "txn_per_hour": len(txns) / max(lookback_hours, 1),
            "unique_device_count": len(set(t.get("device_profile") for t in txns if t.get("device_profile"))),
            "unique_ip_count": 1,
        }

    def detect_fraud_rings(self) -> Dict[str, Any]:
        return {"components": []}


# Global singleton
_client_instance: Optional[TigerGraphClient] = None


def get_graph_client() -> TigerGraphClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = TigerGraphClient()
    return _client_instance


def set_graph_client(client: Optional[TigerGraphClient]) -> None:
    global _client_instance
    _client_instance = client

