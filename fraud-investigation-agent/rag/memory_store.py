"""
rag/memory_store.py
────────────────────
Case memory read/write operations using ChromaDB for vector storage.
Stores resolved case summaries and retrieves similar cases via
semantic embedding similarity over case topology fingerprints.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Try ChromaDB ─────────────────────────────────────────────────────────────
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False
    logger.warning("chromadb not installed — using in-memory dict store.")


# ─── Fallback: in-memory dict store ──────────────────────────────────────────

class _InMemoryStore:
    """Ultra-simple dict-based memory when ChromaDB is unavailable."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict] = {}

    def add(self, case_id: str, document: str, metadata: Dict[str, Any]) -> None:
        self._store[case_id] = {"document": document, "metadata": metadata}

    def query(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        # Simple keyword overlap scoring
        query_words = set(query_text.lower().split())
        results = []
        for case_id, item in self._store.items():
            doc_words = set(item["document"].lower().split())
            score = len(query_words & doc_words) / max(len(query_words), 1)
            results.append({
                "case_id": case_id,
                "similarity": score,
                **item["metadata"],
            })
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

    def count(self) -> int:
        return len(self._store)


# ============================================================
# CaseMemoryStore
# ============================================================

class CaseMemoryStore:
    """
    Persistent memory store for resolved fraud investigation cases.
    Uses ChromaDB if available, falls back to in-memory dict store.
    """

    COLLECTION_NAME = "fraud_case_memory"

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        from config import settings
        self._dir = persist_dir or settings.CHROMA_PERSIST_DIR

        if _CHROMA_AVAILABLE:
            try:
                os.makedirs(self._dir, exist_ok=True)
                self._client = chromadb.PersistentClient(path=self._dir)
                self._collection = self._client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(f"ChromaDB memory store initialised at {self._dir}")
                self._backend = "chroma"
            except Exception as e:
                logger.warning(f"ChromaDB init failed ({e}) — using in-memory store.")
                self._backend = "memory"
                self._mem = _InMemoryStore()
        else:
            self._backend = "memory"
            self._mem = _InMemoryStore()

    def save_case(self, case_id: str, state_dict: Dict[str, Any]) -> bool:
        """
        Persist a resolved case to memory.

        Args:
            case_id:    Unique case identifier.
            state_dict: Serialised FraudAgentState.

        Returns:
            True if successfully saved.
        """
        try:
            document = self._build_document(case_id, state_dict)
            metadata = self._extract_metadata(state_dict)

            if self._backend == "chroma":
                self._collection.upsert(
                    ids=[case_id],
                    documents=[document],
                    metadatas=[metadata],
                )
            else:
                self._mem.add(case_id, document, metadata)

            logger.debug(f"Saved case {case_id} to memory store.")
            return True
        except Exception as e:
            logger.error(f"save_case failed for {case_id}: {e}")
            return False

    def find_similar(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve top-k similar cases via semantic search.

        Args:
            query:  Natural language description of the current case.
            top_k:  Number of results to return.

        Returns:
            List of similar case metadata dicts with similarity scores.
        """
        try:
            if self._backend == "chroma":
                results = self._collection.query(
                    query_texts=[query],
                    n_results=min(top_k, max(self._collection.count(), 1)),
                )
                if not results or not results["ids"][0]:
                    return []
                return [
                    {
                        "case_id":     results["ids"][0][i],
                        "similarity":  1.0 - (results["distances"][0][i] if results.get("distances") else 0.0),
                        **results["metadatas"][0][i],
                    }
                    for i in range(len(results["ids"][0]))
                ]
            else:
                return self._mem.query(query, top_k)
        except Exception as e:
            logger.error(f"find_similar failed: {e}")
            return []

    def _build_document(self, case_id: str, state: Dict[str, Any]) -> str:
        """Build a text document summarising the case for embedding."""
        risk       = state.get("risk_assessment", {})
        evidence   = state.get("graph_evidence", {})
        post_act   = state.get("post_evidence_action", {})

        if hasattr(risk, "dict"):
            risk = risk.dict()
        if hasattr(evidence, "dict"):
            evidence = evidence.dict()
        if hasattr(post_act, "dict"):
            post_act = post_act.dict()

        typology  = risk.get("likely_fraud_type", "UNKNOWN")
        if hasattr(typology, "value"):
            typology = typology.value
        fp        = risk.get("fraud_probability", 0.0)
        unc       = risk.get("uncertainty_score", 0.0)
        action    = post_act.get("action", "")
        if hasattr(action, "value"):
            action = action.value
        devices   = evidence.get("shared_device_accounts", [])
        ips       = evidence.get("shared_ip_accounts", [])
        ring_size = evidence.get("ring_size", 0)

        return (
            f"Case {case_id}: Fraud typology {typology}. "
            f"Fraud probability {fp:.2f}. Uncertainty {unc:.2f}. "
            f"Action taken: {action}. "
            f"Shared device accounts: {len(devices)}. "
            f"Shared IP accounts: {len(ips)}. "
            f"Ring size: {ring_size}. "
            f"Reasoning: {risk.get('reasoning', '')} "
            f"Factors: {', '.join(risk.get('confidence_factors', [])[:5])}. "
        )

    def _extract_metadata(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Extract scalar metadata fields for ChromaDB (must be str/int/float/bool)."""
        risk     = state.get("risk_assessment", {})
        evidence = state.get("graph_evidence", {})
        post_act = state.get("post_evidence_action", {})

        if hasattr(risk, "dict"):     risk = risk.dict()
        if hasattr(evidence, "dict"): evidence = evidence.dict()
        if hasattr(post_act, "dict"): post_act = post_act.dict()

        typology = risk.get("likely_fraud_type", "UNKNOWN")
        if hasattr(typology, "value"):
            typology = typology.value

        action = post_act.get("action", "")
        if hasattr(action, "value"):
            action = action.value

        case_status = state.get("case_status", "")
        if hasattr(case_status, "value"):
            case_status = case_status.value

        return {
            "case_id":         state.get("case_id", ""),
            "fraud_typology":  str(typology),
            "fraud_probability": float(risk.get("fraud_probability", 0.0)),
            "uncertainty_score": float(risk.get("uncertainty_score", 0.0)),
            "post_evidence_action": str(action),
            "sar_required":    bool(state.get("sar_required", False)),
            "case_status":     str(case_status),
            "ring_size":       int(evidence.get("ring_size", 0)),
            "ip_proxy_detected": bool(evidence.get("ip_proxy_detected", False)),
            "saved_at":        datetime.utcnow().isoformat(),
        }

    def count(self) -> int:
        if self._backend == "chroma":
            return self._collection.count()
        return self._mem.count()


# Singleton accessor
_store_instance: Optional[CaseMemoryStore] = None


def get_memory_store() -> CaseMemoryStore:
    global _store_instance
    if _store_instance is None:
        _store_instance = CaseMemoryStore()
    return _store_instance
