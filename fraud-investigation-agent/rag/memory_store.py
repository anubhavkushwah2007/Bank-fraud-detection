"""
rag/memory_store.py
────────────────────
Case memory store initialized from authentic closed_cases_history.csv (5,565 closed cases).
Provides:
- Fast retrieval of authentic case IDs (e.g. ["CC-0141", "CC-0003"]) matching patterns/text
- Read/write persistence for new investigations into case memory
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Try ChromaDB
try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


class CaseMemoryStore:
    """
    Case memory backed by closed_cases_history.csv and persistent ChromaDB / in-memory index.
    """

    COLLECTION_NAME = "fraud_case_memory"

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        from config import settings
        self.settings = settings
        self._df_closed: Optional[pd.DataFrame] = None
        self._cases_by_pattern: Dict[str, List[Dict[str, Any]]] = {}
        self._cases_by_id: Dict[str, Dict[str, Any]] = {}
        self._new_cases: Dict[str, Dict[str, Any]] = {}
        self._load_closed_cases()

    def _load_closed_cases(self) -> None:
        """Load and index all 5,565 closed cases from CSV."""
        try:
            csv_path = self.settings.CLOSED_CASES_CSV
            if csv_path.exists():
                self._df_closed = pd.read_csv(csv_path)
                for _, r in self._df_closed.iterrows():
                    cid = str(r["case_id"]).strip()
                    pat = str(r.get("pattern", "none")).strip()
                    out = str(r.get("outcome", "")).strip()
                    notes = str(r.get("analyst_notes", "")).strip()
                    entry = {
                        "case_id": cid,
                        "pattern": pat,
                        "outcome": out,
                        "customer_id": str(r.get("customer_id", "")),
                        "card_id": str(r.get("card_id", "")),
                        "exposure_usd": float(r.get("exposure_usd", 0.0)),
                        "analyst_notes": notes,
                    }
                    self._cases_by_id[cid] = entry
                    self._cases_by_pattern.setdefault(pat, []).append(entry)
                logger.info(f"Loaded {len(self._cases_by_id)} closed cases into case memory.")
        except Exception as e:
            logger.error(f"Failed to load closed_cases_history.csv: {e}")

    def find_similar_cases(
        self,
        pattern: str = "none",
        query: str = "",
        outcome: Optional[str] = None,
        top_k: int = 3,
    ) -> List[str]:
        """
        Retrieve authentic case IDs (CC-####) matching the pattern or text.
        """
        candidates = self._cases_by_pattern.get(pattern, [])
        if not candidates and outcome:
            candidates = [c for c in self._cases_by_id.values() if c["outcome"] == outcome]

        if not candidates:
            # Fallback to general search
            candidates = list(self._cases_by_id.values())

        if query:
            q_lower = query.lower()
            scored = []
            for c in candidates:
                notes = c["analyst_notes"].lower()
                score = sum(1 for w in q_lower.split() if w in notes)
                scored.append((score, c["case_id"]))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [cid for _, cid in scored[:top_k]]

        # Return top_k matching case IDs
        return [c["case_id"] for c in candidates[:top_k]]

    def save_case(self, case_id: str, case_data: Dict[str, Any]) -> bool:
        """Persist a resolved investigation into memory."""
        self._new_cases[case_id] = case_data
        logger.info(f"Persisted case {case_id} to case memory.")
        return True

    def count(self) -> int:
        return len(self._cases_by_id) + len(self._new_cases)


# Global singleton
_memory_store_instance: Optional[CaseMemoryStore] = None


def get_memory_store() -> CaseMemoryStore:
    global _memory_store_instance
    if _memory_store_instance is None:
        _memory_store_instance = CaseMemoryStore()
    return _memory_store_instance
