"""
config/settings.py
──────────────────
Global configuration for the HHGOA Fraud Investigation Agent.
Supports environment variables from .env and aliases for TigerGraph/Groq.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    BASE_DIR = Path(__file__).resolve().parent.parent
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    BASE_DIR = Path(__file__).resolve().parent.parent

# ─── TigerGraph ────────────────────────────────────────────────────────────────
# Support both TG_* and TIGERGRAPH_* environment variable conventions
TIGERGRAPH_HOST     = os.getenv("TG_HOST", os.getenv("TIGERGRAPH_HOST", "http://localhost"))
TIGERGRAPH_PORT     = int(os.getenv("TG_PORT", os.getenv("TIGERGRAPH_PORT", "14240")))
TIGERGRAPH_GRAPH    = os.getenv("TG_GRAPH_NAME", os.getenv("TIGERGRAPH_GRAPH", "Transaction_Fraud"))
TIGERGRAPH_USERNAME = os.getenv("TG_USERNAME", os.getenv("TIGERGRAPH_USERNAME", "tigergraph"))
TIGERGRAPH_PASSWORD = os.getenv("TG_PASSWORD", os.getenv("TIGERGRAPH_PASSWORD", "tigergraph"))
TIGERGRAPH_SECRET   = os.getenv("TG_SECRET", os.getenv("TIGERGRAPH_SECRET", ""))
TIGERGRAPH_TOKEN    = os.getenv("TG_TOKEN", os.getenv("TIGERGRAPH_TOKEN", ""))

# TG_MODE: 'live' or 'demo'
TG_MODE = os.getenv("TG_MODE", "demo").lower()
DEMO_MODE = TG_MODE != "live" if "TG_MODE" in os.environ else os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")

# ─── LLM Provider (Groq Primary) ───────────────────────────────────────────────
LLM_PROVIDER        = os.getenv("LLM_PROVIDER", "groq")   # groq | google | openai
GROQ_API_KEY        = os.getenv("GROQ_API_KEY", "")
LLM_MODEL           = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "qwen/qwen3.8-27b")
LLM_MAX_RPM         = int(os.getenv("LLM_MAX_RPM", "25"))
LLM_TEMPERATURE     = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# Secondary / Manual Gemini config (5 RPM / 20 RPD free limit)
GOOGLE_API_KEY      = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL        = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# Fallback OpenAI / Anthropic keys (if used)
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")

# ─── Policy & Risk Thresholds (Aligned to Policy v1.0) ─────────────────────────
FRAUD_PROB_HIGH_THRESHOLD   = 0.70  # R1: Single signal with prob < 0.70 requires verify/step-up
STOP_CONFIDENT_FRAUD        = 0.85  # Section 6: Stop when prob >= 0.85
STOP_CONFIDENT_LEGITIMATE   = 0.15  # Section 6: Stop when prob <= 0.15
CREATE_CASE_THRESHOLD       = 0.30  # Section 3a: Open case whenever prob >= 0.30
SAR_EXPOSURE_THRESHOLD      = 1000.0 # Section 3a: File report if exposure > $1,000 or shared link
BLOCK_L1_LIMIT              = 2500.0 # Section 2: L1 for BLOCK_CARD <= $2,500; L2 > $2,500
UNCERTAINTY_EXPOSURE_LIMIT  = 500.0  # R8: Escalate when uncertain and exposure > $500

# ─── Vector Store / RAG ────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR = os.getenv(
    "CHROMA_PERSIST_DIR", str(BASE_DIR / "data" / "chroma_store")
)
EMBEDDING_MODEL    = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
TOP_K_SIMILAR_CASES = int(os.getenv("TOP_K_SIMILAR_CASES", "3"))

# ─── MCP Server ────────────────────────────────────────────────────────────────
MCP_SERVER_HOST = os.getenv("MCP_HOST", os.getenv("MCP_SERVER_HOST", "0.0.0.0"))
MCP_SERVER_PORT = int(os.getenv("MCP_PORT", os.getenv("MCP_SERVER_PORT", "8765")))

# ─── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR       = BASE_DIR / "data"
BENCHMARK_DIR  = DATA_DIR / "benchmark_cases"
CASE_PACK_CSV  = DATA_DIR / "case_pack.csv"
TRANSACTIONS_CSV = DATA_DIR / "transactions.csv"
IDENTITY_CSV   = DATA_DIR / "identity.csv"
CLOSED_CASES_CSV = DATA_DIR / "closed_cases_history.csv"
CASES_OUTPUT_DIR = BASE_DIR / "cases"
POLICIES_PATH  = BASE_DIR / "config" / "fraud_policies.json"
