"""
rag/graph_rag.py
─────────────────
Hybrid GraphRAG retrieval engine combining:
  1. GSQL subgraph extraction (structural evidence)
  2. Policy & typology retrieval (rule-based)
  3. Historical case similarity (ChromaDB vector search)

Produces a unified RAG context string fed to the LLM reasoning nodes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from graph.tigergraph_client import get_graph_client
from rag.memory_store import get_memory_store

logger = logging.getLogger(__name__)

_POLICIES_PATH = Path(__file__).resolve().parent.parent / "config" / "fraud_policies.json"


def _load_policies() -> Dict[str, Any]:
    try:
        with open(_POLICIES_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("fraud_policies.json not found — using empty policy dict.")
        return {}


POLICIES = _load_policies()


# ============================================================
# Policy Retrieval
# ============================================================

def retrieve_policy_context(typology_hint: str, risk_score: float) -> str:
    """
    Retrieve relevant bank policy sections and fraud typology descriptions
    based on detected typology and risk level.

    Returns:
        Formatted policy context string for LLM prompting.
    """
    sections: List[str] = []

    # ── Global risk thresholds ────────────────────────────────────────────────
    thresholds = POLICIES.get("risk_thresholds", {})
    sections.append(
        "BANK POLICY — Risk Thresholds:\n"
        f"  Fraud Alert Threshold:       {thresholds.get('fraud_alert', 0.65):.0%}\n"
        f"  Fraud Block Threshold:       {thresholds.get('fraud_block', 0.75):.0%}\n"
        f"  SAR Mandatory Threshold:     {thresholds.get('sar_mandatory', 0.85):.0%}\n"
        f"  Uncertainty Review Required: {thresholds.get('uncertainty_review', 0.40):.0%}\n"
        f"  Max Daily Amount:            ${thresholds.get('max_daily_amount', 50000):,}\n"
    )

    # ── Typology-specific policy ──────────────────────────────────────────────
    typologies = POLICIES.get("fraud_typologies", {})
    matched_typs = []

    # Exact match
    if typology_hint in typologies:
        matched_typs.append(typologies[typology_hint])

    # Also retrieve top 2 closest typologies by key similarity
    for key, typ in typologies.items():
        if key not in [typology_hint] and len(matched_typs) < 3:
            matched_typs.append(typ)

    for typ in matched_typs[:2]:
        sections.append(
            f"\nFRAUD TYPOLOGY — {typ.get('name', '')}:\n"
            f"  Description:        {typ.get('description', '')}\n"
            f"  Key Signals:        {', '.join(typ.get('key_signals', []))}\n"
            f"  Graph Pattern:      {typ.get('graph_pattern', '')}\n"
            f"  Regulatory Ref:     {typ.get('regulatory_ref', '')}\n"
            f"  SAR Required:       {'YES' if typ.get('sar_required') else 'NO'}\n"
            f"  Recommended Action: {typ.get('recommended_action', '')}\n"
            f"  Approval Required:  {typ.get('approval_tier', '')}\n"
        )

    # ── Authorization matrix ──────────────────────────────────────────────────
    matrix = POLICIES.get("action_authorization_matrix", {})
    sections.append("\nACTION AUTHORIZATION MATRIX:\n")
    for action, spec in matrix.items():
        sections.append(
            f"  {action:<30} → Approval: {spec.get('approval_tier',''):<25} "
            f"SAR: {'YES' if spec.get('sar_required') else 'NO'}\n"
        )

    return "\n".join(sections)


# ============================================================
# Subgraph Evidence Extraction
# ============================================================

def extract_subgraph_evidence(account_id: str, hop_depth: int = 2) -> Dict[str, Any]:
    """
    Extract and analyse the account's neighborhood subgraph.
    Runs shared entity detection, velocity analysis, and ring detection.

    Returns:
        Dict containing all raw graph evidence for the agent.
    """
    client = get_graph_client()
    evidence: Dict[str, Any] = {}

    # ── 1. Shared entity detection ────────────────────────────────────────────
    try:
        shared = client.detect_shared_entities(account_id, window_days=30)
        evidence["shared_device_accounts"] = shared.get("shared_device_accounts", [])
        evidence["shared_ip_accounts"]     = shared.get("shared_ip_accounts", [])
        evidence["shared_card_accounts"]   = shared.get("shared_card_accounts", [])
    except Exception as e:
        logger.error(f"detect_shared_entities failed: {e}")
        evidence["shared_device_accounts"] = []
        evidence["shared_ip_accounts"]     = []
        evidence["shared_card_accounts"]   = []

    # ── 2. Velocity analysis ──────────────────────────────────────────────────
    try:
        velocity = client.trace_velocity(account_id, lookback_hours=72)
        evidence["velocity_burst_score"] = velocity.get("velocity_burst_score", 0.0)
        evidence["txn_per_hour"]         = velocity.get("txn_per_hour", 0.0)
        evidence["unique_device_count"]  = velocity.get("unique_device_count", 0)
        evidence["unique_ip_count"]      = velocity.get("unique_ip_count", 0)
        evidence["total_txn_count"]      = velocity.get("total_txn_count", 0)
        evidence["total_amount"]         = velocity.get("total_amount", 0.0)
    except Exception as e:
        logger.error(f"trace_velocity failed: {e}")

    # ── 3. Fraud ring detection ────────────────────────────────────────────────
    try:
        rings = client.detect_fraud_rings()
        # Find if this account belongs to a ring
        comp_id, ring_size = None, 0
        for comp in rings.get("components", []):
            if account_id in comp.get("members", []):
                comp_id   = comp["component_id"]
                ring_size = comp["size"]
                break
        evidence["ring_component_id"] = comp_id
        evidence["ring_size"]         = ring_size
    except Exception as e:
        logger.error(f"detect_fraud_rings failed: {e}")
        evidence["ring_component_id"] = None
        evidence["ring_size"]         = 0

    # ── 4. Subgraph topology ──────────────────────────────────────────────────
    try:
        subgraph = client.get_subgraph(account_id, hop=hop_depth)
        evidence["nodes"]  = subgraph.get("nodes", [])
        evidence["edges"]  = subgraph.get("edges", [])

        # Check for proxy IPs and new devices in subgraph
        evidence["ip_proxy_detected"]  = any(
            n.get("attributes", {}).get("is_proxy", False)
            for n in evidence.get("nodes", [])
            if n.get("node_type") == "IP_Address"
        )
        ip_countries = [
            n.get("attributes", {}).get("country", "US")
            for n in evidence.get("nodes", [])
            if n.get("node_type") == "IP_Address"
        ]
        evidence["ip_country"] = ip_countries[0] if ip_countries else "US"

        device_nodes = [n for n in evidence.get("nodes", []) if n.get("node_type") == "Device"]
        evidence["new_device_detected"] = any(
            n.get("attributes", {}).get("risk_score", 0.0) > 0.70
            for n in device_nodes
        )

        # Build human-readable subgraph path
        paths = []
        for e in evidence.get("edges", [])[:5]:
            paths.append(f"{e.get('source')} --[{e.get('edge_type')}]--> {e.get('target')}")
        evidence["subgraph_path_summary"] = " | ".join(paths) if paths else "No subgraph paths extracted."

    except Exception as e:
        logger.error(f"get_subgraph failed: {e}")
        evidence.setdefault("nodes", [])
        evidence.setdefault("edges", [])
        evidence.setdefault("ip_proxy_detected", False)
        evidence.setdefault("new_device_detected", False)
        evidence.setdefault("subgraph_path_summary", "")

    return evidence


# ============================================================
# Historical Case Retrieval
# ============================================================

def retrieve_similar_cases(
    typology: str,
    risk_score: float,
    account_id: str,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Retrieve similar historical cases from both ChromaDB memory
    and TigerGraph GSQL similarity query.

    Returns:
        Merged, deduplicated list of similar case dicts.
    """
    results: List[Dict[str, Any]] = []

    # ── ChromaDB semantic search ───────────────────────────────────────────────
    try:
        store = get_memory_store()
        query_text = (
            f"Account {account_id} suspected of {typology} fraud "
            f"with probability {risk_score:.2f}. "
            f"Evidence includes shared devices and proxy IP."
        )
        chroma_results = store.find_similar(query_text, top_k=top_k)
        results.extend(chroma_results)
    except Exception as e:
        logger.warning(f"ChromaDB similar case search failed: {e}")

    # ── TigerGraph GSQL similarity ────────────────────────────────────────────
    try:
        client = get_graph_client()
        tg_results = client.find_similar_cases(typology, risk_score, top_k=top_k)
        # Merge, dedup by case_id
        existing_ids = {r.get("case_id") for r in results}
        for r in tg_results:
            if r.get("case_id") not in existing_ids:
                results.append(r)
                existing_ids.add(r.get("case_id"))
    except Exception as e:
        logger.warning(f"TigerGraph similar case search failed: {e}")

    # Sort by similarity descending
    results.sort(key=lambda x: x.get("similarity", x.get("similarity_score", 0.0)), reverse=True)
    return results[:top_k]


# ============================================================
# Unified RAG Context Builder
# ============================================================

def build_rag_context(
    account_id: str,
    typology_hint: str = "UNKNOWN",
    risk_score: float = 0.0,
    similar_cases: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Build the complete RAG context string for LLM reasoning.
    Combines policy rules, typology descriptions, and similar cases.

    Args:
        account_id:     Account being investigated.
        typology_hint:  Best-guess fraud typology.
        risk_score:     Current fraud probability estimate.
        similar_cases:  Pre-fetched similar cases (optional).

    Returns:
        Formatted multi-section RAG context string.
    """
    parts: List[str] = ["=" * 60, "GRAPHRAG CONTEXT — FRAUD INVESTIGATION", "=" * 60]

    # ── Policy & Typology ──────────────────────────────────────────────────────
    policy_ctx = retrieve_policy_context(typology_hint, risk_score)
    parts.append(policy_ctx)

    # ── Similar Cases ──────────────────────────────────────────────────────────
    if similar_cases is None:
        similar_cases = retrieve_similar_cases(typology_hint, risk_score, account_id)

    if similar_cases:
        parts.append("\nHISTORICAL SIMILAR CASES:")
        for i, c in enumerate(similar_cases[:3], 1):
            sim = c.get("similarity", c.get("similarity_score", 0.0))
            parts.append(
                f"  [{i}] Case {c.get('case_id','?')}: "
                f"Typology={c.get('fraud_typology','?')}, "
                f"Risk={c.get('final_risk', 0.0):.2f}, "
                f"Action={c.get('post_evidence_action','?')}, "
                f"SAR={c.get('sar_required','?')}, "
                f"Similarity={sim:.2f}"
            )
    else:
        parts.append("\nHISTORICAL SIMILAR CASES: No prior cases found in memory.")

    parts.append("=" * 60)
    return "\n".join(parts)
