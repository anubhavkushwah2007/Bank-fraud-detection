"""
graph/tigergraph_client.py
──────────────────────────
pyTigerGraph wrapper with auto-fallback to NetworkX mock mode.
All methods return consistent dicts regardless of backend.

Live mode:   Connects to TigerGraph via pyTigerGraph / REST++ API.
Demo mode:   Uses a pre-seeded NetworkX in-memory graph.
"""
from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import networkx as nx

logger = logging.getLogger(__name__)

# ─── Try to import pyTigerGraph ───────────────────────────────────────────────
try:
    import pyTigerGraph as tg  # type: ignore
    _TG_AVAILABLE = True
except ImportError:
    _TG_AVAILABLE = False
    logger.warning("pyTigerGraph not installed — running in mock/demo mode.")


# ============================================================
# Mock Graph (NetworkX) — used when DEMO_MODE=true or TG unavailable
# ============================================================

class MockFraudGraph:
    """
    In-memory NetworkX multigraph simulating TigerGraph for demo purposes.
    Pre-seeded with realistic fraud network structure.
    """

    def __init__(self) -> None:
        self.G = nx.MultiDiGraph()
        self._cases: Dict[str, Dict] = {}
        self._rng = random.Random(42)
        self._seed_demo_graph()

    def _seed_demo_graph(self) -> None:
        """Seed a realistic fraud scenario graph."""
        # Accounts
        accs = [
            ("ACC_001", {"status": "ACTIVE",  "risk_baseline": 0.2, "risk_score_current": 0.85}),
            ("ACC_002", {"status": "ACTIVE",  "risk_baseline": 0.1, "risk_score_current": 0.78}),
            ("ACC_003", {"status": "FROZEN",  "risk_baseline": 0.5, "risk_score_current": 0.92}),
            ("ACC_004", {"status": "ACTIVE",  "risk_baseline": 0.1, "risk_score_current": 0.45}),
            ("ACC_005", {"status": "ACTIVE",  "risk_baseline": 0.3, "risk_score_current": 0.67}),
            ("ACC_006", {"status": "WATCHLIST","risk_baseline": 0.4, "risk_score_current": 0.72}),
        ]
        for acc_id, attrs in accs:
            self.G.add_node(acc_id, node_type="Account", **attrs)

        # Devices
        devs = [
            ("DEV_001", {"device_info": "Chrome/Linux",  "is_emulator": False, "risk_score": 0.8}),
            ("DEV_002", {"device_info": "Safari/iOS",    "is_emulator": False, "risk_score": 0.2}),
            ("DEV_003", {"device_info": "Emulator/Android","is_emulator": True,"risk_score": 0.95}),
        ]
        for d_id, attrs in devs:
            self.G.add_node(d_id, node_type="Device", **attrs)

        # IPs
        ips = [
            ("IP_001", {"country": "RU", "is_proxy": True,  "is_vpn": True,  "abuse_confidence": 0.9}),
            ("IP_002", {"country": "US", "is_proxy": False, "is_vpn": False, "abuse_confidence": 0.1}),
            ("IP_003", {"country": "NG", "is_proxy": True,  "is_vpn": False, "abuse_confidence": 0.8}),
        ]
        for ip_id, attrs in ips:
            self.G.add_node(ip_id, node_type="IP_Address", **attrs)

        # Cards
        cards = [
            ("CARD_001", {"card_type": "VISA", "is_compromised": True}),
            ("CARD_002", {"card_type": "MC",   "is_compromised": False}),
        ]
        for c_id, attrs in cards:
            self.G.add_node(c_id, node_type="Card", **attrs)

        # Transactions
        base_ts = datetime.utcnow()
        txns = [
            ("TXN_001", {"amount": 8900.0,  "risk_score": 0.87, "timestamp": str(base_ts - timedelta(hours=2))}),
            ("TXN_002", {"amount": 9800.0,  "risk_score": 0.91, "timestamp": str(base_ts - timedelta(hours=1))}),
            ("TXN_003", {"amount": 450.0,   "risk_score": 0.45, "timestamp": str(base_ts - timedelta(hours=6))}),
            ("TXN_004", {"amount": 12500.0, "risk_score": 0.93, "timestamp": str(base_ts - timedelta(minutes=30))}),
        ]
        for t_id, attrs in txns:
            self.G.add_node(t_id, node_type="Transaction", **attrs)

        # Edges — fraud ring: ACC_001, ACC_002, ACC_003 all using DEV_001 and IP_001
        edges = [
            ("ACC_001", "TXN_001", "PERFORMED_TRANSACTION"),
            ("ACC_002", "TXN_002", "PERFORMED_TRANSACTION"),
            ("ACC_003", "TXN_004", "PERFORMED_TRANSACTION"),
            ("ACC_004", "TXN_003", "PERFORMED_TRANSACTION"),
            ("TXN_001", "DEV_001", "USED_DEVICE"),
            ("TXN_002", "DEV_001", "USED_DEVICE"),  # shared device!
            ("TXN_004", "DEV_001", "USED_DEVICE"),  # shared device!
            ("TXN_003", "DEV_002", "USED_DEVICE"),
            ("TXN_001", "IP_001",  "USED_IP"),
            ("TXN_002", "IP_001",  "USED_IP"),   # shared proxy IP!
            ("TXN_004", "IP_001",  "USED_IP"),   # shared proxy IP!
            ("TXN_003", "IP_002",  "USED_IP"),
            ("TXN_001", "CARD_001","USED_CARD"),
            ("TXN_002", "CARD_001","USED_CARD"),  # shared compromised card!
            ("TXN_004", "CARD_001","USED_CARD"),
            ("TXN_003", "CARD_002","USED_CARD"),
        ]
        for src, tgt, edge_type in edges:
            self.G.add_edge(src, tgt, edge_type=edge_type)

    def get_node_attrs(self, node_id: str) -> Dict[str, Any]:
        return dict(self.G.nodes.get(node_id, {}))

    def get_neighbors(self, node_id: str, hop: int = 2) -> List[Dict[str, Any]]:
        """BFS up to `hop` hops from node_id."""
        visited = set()
        frontier = [node_id]
        result = []
        for _ in range(hop):
            next_frontier = []
            for n in frontier:
                for nb in list(self.G.successors(n)) + list(self.G.predecessors(n)):
                    if nb not in visited:
                        visited.add(nb)
                        attrs = self.get_node_attrs(nb)
                        attrs["node_id"] = nb
                        result.append(attrs)
                        next_frontier.append(nb)
            frontier = next_frontier
        return result

    def detect_shared_entities(self, account_id: str, window_days: int = 30) -> Dict[str, Any]:
        """Find accounts sharing Device/IP/Card with the given account."""
        # Find this account's transactions
        own_txns = [n for n, _ in self.G.out_edges(account_id)
                    if self.G.nodes[n].get("node_type") == "Transaction"]

        shared_device_accs, shared_ip_accs, shared_card_accs = set(), set(), set()

        for txn in own_txns:
            for entity in self.G.successors(txn):
                etype = self.G.nodes[entity].get("node_type", "")
                # Find other transactions using the same entity
                for other_txn in self.G.predecessors(entity):
                    if other_txn == txn or self.G.nodes[other_txn].get("node_type") != "Transaction":
                        continue
                    # Find account of other_txn
                    for other_acc in self.G.predecessors(other_txn):
                        if (self.G.nodes[other_acc].get("node_type") == "Account"
                                and other_acc != account_id):
                            if etype == "Device":
                                shared_device_accs.add(other_acc)
                            elif etype == "IP_Address":
                                shared_ip_accs.add(other_acc)
                            elif etype == "Card":
                                shared_card_accs.add(other_acc)

        return {
            "shared_device_accounts": list(shared_device_accs),
            "shared_ip_accounts":     list(shared_ip_accs),
            "shared_card_accounts":   list(shared_card_accs),
        }

    def trace_velocity(self, account_id: str, lookback_hours: int = 72) -> Dict[str, Any]:
        """Compute transaction velocity metrics."""
        own_txns = [
            (n, self.G.nodes[n])
            for n, _ in self.G.out_edges(account_id)
            if self.G.nodes[n].get("node_type") == "Transaction"
        ]
        total   = len(own_txns)
        amounts = [attr.get("amount", 0.0) for _, attr in own_txns]
        total_amount = sum(amounts)
        unique_devs  = set()
        unique_ips   = set()
        for txn_id, _ in own_txns:
            for nb in self.G.successors(txn_id):
                if self.G.nodes[nb].get("node_type") == "Device":
                    unique_devs.add(nb)
                if self.G.nodes[nb].get("node_type") == "IP_Address":
                    unique_ips.add(nb)
        txn_per_hour = total / max(lookback_hours, 1)
        burst = txn_per_hour * (1 + len(unique_devs)) * (1 + len(unique_ips))
        return {
            "total_txn_count":    total,
            "total_amount":       total_amount,
            "avg_txn_amount":     total_amount / max(total, 1),
            "max_txn_amount":     max(amounts, default=0.0),
            "txn_per_hour":       txn_per_hour,
            "unique_device_count": len(unique_devs),
            "unique_ip_count":    len(unique_ips),
            "velocity_burst_score": burst,
        }

    def detect_fraud_rings(self) -> Dict[str, Any]:
        """Run WCC on Account nodes connected by SHARED_IDENTITY logic."""
        accs = [n for n in self.G.nodes if self.G.nodes[n].get("node_type") == "Account"]
        # Build undirected identity graph from shared device/IP
        G_id = nx.Graph()
        for acc in accs:
            G_id.add_node(acc)
        # If two accounts share a device or IP they're connected
        shared = {}
        for acc in accs:
            info = self.detect_shared_entities(acc)
            for other in info["shared_device_accounts"] + info["shared_ip_accounts"]:
                if other in accs:
                    G_id.add_edge(acc, other)

        components = list(nx.connected_components(G_id))
        return {
            "components": [
                {"component_id": f"COMP_{i}", "members": list(c), "size": len(c)}
                for i, c in enumerate(components)
            ],
            "total_components": len(components),
            "largest_ring_size": max((len(c) for c in components), default=0),
        }

    def get_subgraph(self, account_id: str, hop: int = 2) -> Dict[str, Any]:
        """Extract n-hop subgraph around an account."""
        nodes_raw = self.get_neighbors(account_id, hop)
        # Add source node
        src_attrs = self.get_node_attrs(account_id)
        src_attrs["node_id"] = account_id
        nodes_raw.insert(0, src_attrs)

        nodes = [{"node_id": n["node_id"], "node_type": n.get("node_type", "Unknown"),
                  "attributes": {k: v for k, v in n.items() if k not in ("node_id", "node_type")}}
                 for n in nodes_raw]

        edges = []
        node_ids = {n["node_id"] for n in nodes}
        for src, tgt, data in self.G.edges(data=True):
            if src in node_ids and tgt in node_ids:
                edges.append({"source": src, "target": tgt, "edge_type": data.get("edge_type", ""),
                               "attributes": {}})
        return {"nodes": nodes, "edges": edges}

    def upsert_case(self, case_id: str, case_data: Dict[str, Any]) -> bool:
        self._cases[case_id] = {**case_data, "updated_at": datetime.utcnow().isoformat()}
        return True

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        return self._cases.get(case_id)

    def find_similar_cases(self, typology: str, risk: float, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return mock similar historical cases."""
        mock_cases = [
            {"case_id": "HIST_001", "fraud_typology": "ACCOUNT_TAKEOVER",    "final_risk": 0.91, "post_evidence_action": "FREEZE_ACCOUNT", "sar_required": True,  "similarity_score": 0.95},
            {"case_id": "HIST_002", "fraud_typology": "CARD_NOT_PRESENT_RING","final_risk": 0.82, "post_evidence_action": "BLOCK_TRANSACTION","sar_required": False, "similarity_score": 0.87},
            {"case_id": "HIST_003", "fraud_typology": "SYNTHETIC_IDENTITY",   "final_risk": 0.95, "post_evidence_action": "FILE_SAR",        "sar_required": True,  "similarity_score": 0.80},
            {"case_id": "HIST_004", "fraud_typology": "SMURFING_VELOCITY",    "final_risk": 0.88, "post_evidence_action": "FILE_SAR",        "sar_required": True,  "similarity_score": 0.75},
            {"case_id": "HIST_005", "fraud_typology": "BUST_OUT",             "final_risk": 0.79, "post_evidence_action": "ACCOUNT_HOLD",    "sar_required": False, "similarity_score": 0.70},
        ]
        # Filter and sort by typology match + risk proximity
        for c in mock_cases:
            c["similarity_score"] = (
                0.5 + (0.4 if c["fraud_typology"] == typology else 0.0)
                + 0.1 * (1.0 - abs(c["final_risk"] - risk))
            )
        return sorted(mock_cases, key=lambda x: x["similarity_score"], reverse=True)[:top_k]


# ============================================================
# Live TigerGraph Client
# ============================================================

class LiveTigerGraphClient:
    """Thin wrapper over pyTigerGraph for live TigerGraph connections."""

    def __init__(self, host: str, graph: str, username: str, password: str,
                 secret: str = "", token: str = "") -> None:
        if not _TG_AVAILABLE:
            raise ImportError("pyTigerGraph package is required for live mode.")
        self.conn = tg.TigerGraphConnection(
            host=host,
            graphname=graph,
            username=username,
            password=password,
        )
        if token:
            self.conn.apiToken = token
        elif secret:
            self.conn.getToken(secret)
        logger.info(f"Connected to TigerGraph: {host} / {graph}")

    def _run_query(self, query_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            result = self.conn.runInstalledQuery(query_name, params=params)
            return result[0] if result else {}
        except Exception as e:
            logger.error(f"GSQL query '{query_name}' failed: {e}")
            return {}

    def detect_shared_entities(self, account_id: str, window_days: int = 30) -> Dict[str, Any]:
        return self._run_query("detect_shared_entities", {"acc": account_id, "window_days": window_days})

    def trace_velocity(self, account_id: str, lookback_hours: int = 72) -> Dict[str, Any]:
        return self._run_query("trace_fund_velocity", {"acc": account_id, "lookback_hours": lookback_hours})

    def detect_fraud_rings(self) -> Dict[str, Any]:
        return self._run_query("graph_fraud_ring_detection", {"min_ring_risk": 0.60, "min_ring_size": 3})

    def find_similar_cases(self, typology: str, risk: float, top_k: int = 5) -> List[Dict[str, Any]]:
        result = self._run_query("find_similar_cases", {"query_typology": typology, "query_risk": risk, "top_k": top_k})
        return result.get("top_cases", [])

    def get_subgraph(self, account_id: str, hop: int = 2) -> Dict[str, Any]:
        try:
            vertices = self.conn.getVerticesById("Account", [account_id])
            neighbors = self.conn.getEdgesBySourceVertex("Account", account_id)
            return {"nodes": vertices, "edges": neighbors}
        except Exception as e:
            logger.error(f"get_subgraph failed: {e}")
            return {"nodes": [], "edges": []}

    def upsert_case(self, case_id: str, case_data: Dict[str, Any]) -> bool:
        try:
            self.conn.upsertVertex("Case", case_id, attributes=case_data)
            return True
        except Exception as e:
            logger.error(f"upsert_case failed: {e}")
            return False

    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        try:
            result = self.conn.getVerticesById("Case", [case_id])
            return result[0] if result else None
        except Exception as e:
            logger.error(f"get_case failed: {e}")
            return None


# ============================================================
# Factory — returns correct client based on config
# ============================================================

_mock_instance: Optional[MockFraudGraph] = None


def get_graph_client(demo_mode: Optional[bool] = None) -> Any:
    """
    Factory that returns the appropriate graph client.

    Args:
        demo_mode: Override; if None reads from config.settings.DEMO_MODE.
    """
    global _mock_instance

    from config import settings

    use_demo = demo_mode if demo_mode is not None else settings.DEMO_MODE

    if use_demo or not _TG_AVAILABLE:
        if _mock_instance is None:
            logger.info("Initialising MockFraudGraph (demo mode).")
            _mock_instance = MockFraudGraph()
        return _mock_instance

    logger.info("Connecting to live TigerGraph instance.")
    return LiveTigerGraphClient(
        host     = settings.TIGERGRAPH_HOST,
        graph    = settings.TIGERGRAPH_GRAPH,
        username = settings.TIGERGRAPH_USERNAME,
        password = settings.TIGERGRAPH_PASSWORD,
        secret   = settings.TIGERGRAPH_SECRET,
        token    = settings.TIGERGRAPH_TOKEN,
    )
