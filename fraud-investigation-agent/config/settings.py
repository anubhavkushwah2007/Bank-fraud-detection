"""
Global configuration for the HHGOA Fraud Investigation Agent.
All values can be overridden via environment variables or a .env file.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    BASE_DIR = Path(__file__).resolve().parent.parent
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    BASE_DIR = Path(__file__).resolve().parent.parent

# ─── TigerGraph ────────────────────────────────────────────────────────────────
TIGERGRAPH_HOST     = os.getenv("TIGERGRAPH_HOST",     "http://localhost")
TIGERGRAPH_PORT     = int(os.getenv("TIGERGRAPH_PORT", "14240"))
TIGERGRAPH_GRAPH    = os.getenv("TIGERGRAPH_GRAPH",    "FraudGraph")
TIGERGRAPH_USERNAME = os.getenv("TIGERGRAPH_USERNAME", "tigergraph")
TIGERGRAPH_PASSWORD = os.getenv("TIGERGRAPH_PASSWORD", "tigergraph")
TIGERGRAPH_SECRET   = os.getenv("TIGERGRAPH_SECRET",   "")
TIGERGRAPH_TOKEN    = os.getenv("TIGERGRAPH_TOKEN",    "")

# Demo/Mock mode — set DEMO_MODE=false to connect to a live TigerGraph instance
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")

# ─── LLM ───────────────────────────────────────────────────────────────────────
LLM_PROVIDER     = os.getenv("LLM_PROVIDER",     "openai")   # openai | anthropic | google
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY",   "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY   = os.getenv("GOOGLE_API_KEY",   "")
LLM_MODEL        = os.getenv("LLM_MODEL",        "gpt-4o")
LLM_TEMPERATURE  = float(os.getenv("LLM_TEMPERATURE", "0.1"))

# ─── Risk Thresholds ───────────────────────────────────────────────────────────
FRAUD_THRESHOLD        = float(os.getenv("FRAUD_THRESHOLD",        "0.75"))
UNCERTAINTY_THRESHOLD  = float(os.getenv("UNCERTAINTY_THRESHOLD",  "0.40"))
SAR_THRESHOLD          = float(os.getenv("SAR_THRESHOLD",          "0.85"))
VELOCITY_SPIKE_FACTOR  = float(os.getenv("VELOCITY_SPIKE_FACTOR",  "3.0"))

# ─── Vector Store ──────────────────────────────────────────────────────────────
CHROMA_PERSIST_DIR = os.getenv(
    "CHROMA_PERSIST_DIR", str(BASE_DIR / "data" / "chroma_db")
)
EMBEDDING_MODEL    = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
TOP_K_SIMILAR_CASES = int(os.getenv("TOP_K_SIMILAR_CASES", "5"))

# ─── Agent ─────────────────────────────────────────────────────────────────────
MAX_EVIDENCE_RETRIES = int(os.getenv("MAX_EVIDENCE_RETRIES", "2"))
HOP_DEPTH            = int(os.getenv("HOP_DEPTH", "2"))

# ─── MCP Server ────────────────────────────────────────────────────────────────
MCP_SERVER_HOST = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8765"))

# ─── Paths ─────────────────────────────────────────────────────────────────────
BENCHMARK_DIR  = BASE_DIR / "data" / "benchmark_cases"
RESULTS_DIR    = BASE_DIR / "eval" / "results"
POLICIES_PATH  = BASE_DIR / "config" / "fraud_policies.json"
