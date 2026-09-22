# HHGOA Fraud Investigation Agent — README

<div align="center">

```
╔═══════════════════════════════════════════════════════════╗
║  HHGOA  │  Agentic Fraud Investigation System            ║
║  TigerGraph + LangGraph + GraphRAG + Streamlit           ║
╚═══════════════════════════════════════════════════════════╝
```

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![TigerGraph](https://img.shields.io/badge/TigerGraph-MCP-orange.svg)](https://tigergraph.com)

</div>

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    ANALYST DASHBOARD (Streamlit)                 │
│        Case Queue │ Graph View │ Approval Queue │ Analytics      │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│              LANGGRAPH AGENT WORKFLOW (8 Stages)                 │
│  Trigger → Investigate → GraphRAG → Assess Risk → Pre-NBA       │
│    → Extra Evidence (conditional loop) → Post-NBA → SAR → Memory│
└────────────┬───────────────────────────┬────────────────────────┘
             │                           │
┌────────────▼──────────┐  ┌────────────▼──────────────────────┐
│   TIGERGRAPH          │  │   RAG LAYER                        │
│   Graph Schema        │  │   ChromaDB Vector Store            │
│   GSQL Queries:       │  │   Policy & Typology Retrieval      │
│   • detect_shared     │  │   Historical Case Similarity       │
│   • trace_velocity    │  └───────────────────────────────────┘
│   • ring_detection    │
│   • find_similar      │  ┌───────────────────────────────────┐
│   TigerGraph MCP      │  │   MOCK EXTERNAL ACTIONS            │
│   (FastAPI adapter)   │  │   • Step-Up MFA / OTP              │
└───────────────────────┘  │   • Customer SMS/Email             │
                           │   • Card Freeze                    │
                           │   • Account Hold / Freeze          │
                           │   • SAR Filing                     │
                           └───────────────────────────────────┘
```

## 📋 5 Fraud Typologies

| ID      | Typology                    | Key Signal                        | Action            |
|---------|-----------------------------|-----------------------------------|-------------------|
| TYP-001 | Card-Not-Present Ring       | Shared device, cross-merchant     | BLOCK_TRANSACTION |
| TYP-002 | Account Takeover            | New device + foreign proxy IP     | FREEZE_ACCOUNT    |
| TYP-003 | Bust-Out                    | Credit burst + address change     | ACCOUNT_HOLD      |
| TYP-004 | Synthetic Identity          | WCC ring, shared hardware         | FILE_SAR          |
| TYP-005 | Smurfing / Velocity         | Sub-$10k velocity burst           | FILE_SAR          |

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd fraud-investigation-agent
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env — at minimum, add your LLM API key (optional for demo mode)
```

### 3. Generate Benchmark Cases

```bash
python data/generate_benchmark.py
```

### 4. Run the Dashboard

```bash
streamlit run ui/app.py
```

### 5. Run Benchmark Evaluation (20 cases)

```bash
python eval/run_benchmark.py --verbose
```

---

## 🗂️ Directory Structure

```
fraud-investigation-agent/
├── config/
│   ├── settings.py              # All config with env var overrides
│   └── fraud_policies.json      # 5 typologies, authorization matrix, SAR rules
├── gsql/
│   ├── schema.gsql              # Full TigerGraph schema (8 vertex types, 9 edge types)
│   ├── queries/
│   │   ├── detect_shared_entities.gsql
│   │   ├── trace_fund_velocity.gsql
│   │   ├── fraud_ring_detection.gsql  (WCC label propagation)
│   │   └── find_similar_cases.gsql
│   └── setup_graph.sh           # Bootstrap script for TigerGraph
├── data/
│   ├── ingest_ieee.py           # CSV loader + synthetic data generator
│   ├── generate_benchmark.py    # 20 test case generator
│   └── benchmark_cases/         # HHG-001.json ... HHG-020.json
├── graph/
│   ├── tigergraph_client.py     # pyTigerGraph wrapper + NetworkX mock
│   └── mcp_server.py            # FastAPI MCP adapter (port 8765)
├── rag/
│   ├── graph_rag.py             # Hybrid retrieval: GSQL + ChromaDB
│   └── memory_store.py          # Case memory read/write (ChromaDB)
├── agent/
│   ├── state.py                 # Pydantic models + LangGraph TypedDict
│   ├── workflow.py              # 8-stage LangGraph state machine
│   ├── tools.py                 # 8 mock external action tools
│   ├── policy_engine.py         # NBA decision matrix, SAR determination
│   └── sar_generator.py         # FinCEN-compliant SAR draft generator
├── eval/
│   └── run_benchmark.py         # Automated 20-case evaluation runner
├── ui/
│   └── app.py                   # Streamlit analyst dashboard (6 pages)
├── .env.example
├── requirements.txt
└── README.md
```

## 🔌 TigerGraph Setup (Optional — skip for demo mode)

```bash
# 1. Bootstrap the graph schema and queries
bash gsql/setup_graph.sh

# 2. Ingest data
python data/ingest_ieee.py --synthetic --num-accounts 5000

# 3. Start the MCP server
uvicorn graph.mcp_server:app --host 0.0.0.0 --port 8765
```

## 🧠 Agent Lifecycle (8 Stages)

```
[Trigger] ──> [Investigate Subgraph] ──> [Gather GraphRAG Evidence]
    ──> [Assess Risk & Uncertainty]
         ├── uncertainty > 40% ──> [Extra Evidence: MFA / Outreach] ──> (loop back)
         └── threshold met ──> [Post-Evidence NBA Decision]
                               ──> [SAR & Explainability]
                               ──> [Update Case Memory in Graph]
```

## 📊 Benchmark Output Format

Each case produces `eval/results/CASE_2026_XXX_result.json`:

```json
{
  "case_id": "CASE_2026_001",
  "initial_trigger": {...},
  "pre_evidence_recommendation": {
    "action": "STEP_UP_AUTH",
    "approval_required": "AUTOMATED_POLICY",
    "confidence": 0.82
  },
  "additional_evidence_gathered": {
    "action_taken": "STEP_UP_MFA",
    "response_received": "TRANSACTION_UNRECOGNIZED"
  },
  "post_evidence_recommendation": {
    "action": "FREEZE_ACCOUNT",
    "approval_required": "TIER_2_ANALYST",
    "confidence": 0.94,
    "fraud_typology": "ACCOUNT_TAKEOVER"
  },
  "graph_evidence": {
    "shared_device_accounts_count": 2,
    "ip_proxy_detected": true,
    "subgraph_path": "ACC_001 --[USED_DEVICE]--> DEV_NEW_001"
  },
  "sar_filing_required": true,
  "sar_draft": "SUSPICIOUS ACTIVITY REPORT...",
  "audit_trail": [...]
}
```

## 🔧 Tech Stack

| Layer         | Technology                           |
|---------------|--------------------------------------|
| Graph DB      | TigerGraph (GSQL, WCC, PageRank)     |
| Agent         | LangGraph 0.2+ / Python 3.11         |
| LLM           | OpenAI GPT-4o / Anthropic / Gemini   |
| Vector Store  | ChromaDB                             |
| GraphRAG      | GSQL + ChromaDB Hybrid               |
| MCP Adapter   | FastAPI + uvicorn                    |
| Dashboard     | Streamlit + Plotly + Pyvis           |
| Dataset       | IEEE-CIS Fraud Detection (synthetic) |

## 📝 License

Built for HHGOA Hackathon 2026. MIT License.
