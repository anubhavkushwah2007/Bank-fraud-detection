[README.md](https://github.com/user-attachments/files/32637329/README.md)
# HHGOA Fraud Investigation Agent — README

<div align="center">

```
╔═══════════════════════════════════════════════════════════╗
║  HHGOA  │  Agentic Fraud Investigation System            ║
║  TigerGraph + LangGraph + GraphRAG + Vision UI           ║
╚═══════════════════════════════════════════════════════════╝
```

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![TigerGraph](https://img.shields.io/badge/TigerGraph-MCP-orange.svg)](https://tigergraph.com)
[![Frontend](https://img.shields.io/badge/Frontend-Vision%20UI-brightgreen.svg)](#️-frontend-dashboard)

</div>

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│              VISION UI DASHBOARD (HTML / CSS / JS)               │
│  Home · Investigate · Case Viewer · Graph View · Approval Queue  │
│  Analytics · System Info                                         │
└────────────────────────────┬────────────────────────────────────┘
                             │ REST API (server.py on :8000)
┌────────────────────────────▼────────────────────────────────────┐
│              LANGGRAPH AGENT WORKFLOW (8 Stages)                 │
│  Trigger → Investigate → GraphRAG → Assess Risk → Pre-NBA       │
│    → Extra Evidence (conditional loop) → Post-NBA → SAR → Memory│
└────────────┬───────────────────────────┬────────────────────────┘
             │                           │
┌────────────▼──────────┐  ┌────────────▼──────────────────────┐
│   TIGERGRAPH CLOUD    │  │   RAG LAYER                        │
│   Graph Schema        │  │   ChromaDB Vector Store            │
│   GSQL Queries:       │  │   Policy & Typology Retrieval      │
│   • detect_shared     │  │   Historical Case Similarity       │
│   • trace_velocity    │  └───────────────────────────────────┘
│   • ring_detection    │
│   • find_similar      │  ┌───────────────────────────────────┐
│   TigerGraph MCP      │  │   ACTIONS & EVIDENCE TOOLS         │
│   (FastAPI adapter)   │  │   • Step-Up MFA / OTP              │
└───────────────────────┘  │   • Customer Outreach              │
                           │   • Card Freeze                    │
                           │   • Account Hold / Freeze          │
                           │   • FinCEN SAR Filing              │
                           └───────────────────────────────────┘
```

---

## 🖥️ Frontend Dashboard

The primary interface is a **premium Vision UI-inspired dashboard** built with vanilla HTML, CSS, and JavaScript, served seamlessly via `server.py` with real-time API routes.

### Pages
- **Home** — Live KPI mini-cards, threat mitigation index, velocity trend chart, typology breakdown, dynamic case queue, and real-time agent activity feed.
- **Investigate** — Account ID / transaction lookup, interactive LangGraph 8-stage state machine visualizer, evidence signals breakdown, and Next Best Action (NBA) recommendations.
- **Case Viewer** — Live dossier inspector populated from verified cases (`cases/HHG-*.json`), complete with risk indicators, evidence matrices, and full FinCEN SAR drafts.
- **Graph View** — Interactive TigerGraph subgraph canvas rendering connected transaction, card, device, and customer entities.
- **Approval Queue** — Governance queue for analyst sign-off (Automated, Tier-1 Lead, Tier-2 Fraud Manager).
- **Analytics** — Longitudinal trends, typology distributions, precision/recall curves, and benchmark evaluation metrics.
- **System Info** — Component health checks (TigerGraph, LLM, Vector Store, MCP), schema specification, and workflow pipeline visualizer.

### Design System
| Token | Value |
|---|---|
| Primary BG | `#02120a` (Deep Forest) |
| Accent Emerald | `#10b981` |
| Accent Gold | `#f59e0b` |
| Accent Coral | `#f43f5e` |
| Card style | Glassmorphism, 20px radius |
| Typography | Inter + JetBrains Mono |

---

## 📋 5 Fraud Typologies

| ID      | Typology                    | Key Signal                        | Action            |
|---------|-----------------------------|-----------------------------------|-------------------|
| TYP-001 | Card-Not-Present Ring       | Shared device, cross-merchant     | BLOCK_TRANSACTION |
| TYP-002 | Account Takeover            | New device + foreign proxy IP     | FREEZE_ACCOUNT    |
| TYP-003 | Bust-Out                    | Credit burst + address change     | ACCOUNT_HOLD      |
| TYP-004 | Synthetic Identity          | WCC ring, shared hardware         | FILE_SAR          |
| TYP-005 | Smurfing / Velocity         | Sub-$10k velocity burst           | FILE_SAR          |

---

## 🚀 Authentic Quick Start

### 1. Install Dependencies

```bash
cd fraud-investigation-agent
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy `.env.example` to `.env` if you have not already:
```bash
cp .env.example .env
```
Ensure your `.env` contains:
- `TG_HOST` (e.g., `https://tg-xxx.i.tgcloud.io`)
- `TG_GRAPH_NAME` (e.g., `FraudGraph` or `MyGraph`)
- `TG_SECRET` / `TG_TOKEN` (TigerGraph Cloud authorization secret/token)
- `TG_TGCLOUD=true`
- `TG_SSL_PORT=443`
- `OPENAI_API_KEY` (or other LLM provider key)
- `STRICT_GRAPH=true` (defaults to `true`)
- `OFFLINE_DEV=false` (defaults to `false` for live graph enforcement)

> [!IMPORTANT]
> Never commit your `.env` file to version control.

### 3. Verify Dataset Placement

The system expects authentic datasets placed under `data_real/` (or configured via `DATA_DIR`):
- `data_real/transactions.csv` (IEEE-CIS transactions with `risk_score` and `customer_id`)
- `data_real/identity.csv` (Device and identity network attributes)
- `data_real/closed_cases_history.csv` (5,565 historical investigations for GraphRAG memory)
- `data_real/case_pack.csv` (20 evaluation benchmark cases HHG-001 to HHG-020)

### 4. Run Pre-Flight Setup Verification

Run the setup diagnostic script to validate environment keys, dataset files, live TigerGraph reachability, and vertex counts:
```bash
python scripts/check_setup.py
```
> [!NOTE]
> If TigerGraph Cloud is sleeping or unreachable, `check_setup.py` will report connection failure and exit with non-zero code. For local offline experimentation, set `OFFLINE_DEV=true` in `.env`.

### 5. Run Benchmark Evaluation (20 Cases)

Run the full autonomous multi-agent evaluation over the 20 benchmark cases:
```bash
python eval/run_benchmark.py --verbose
```

#### The `--verbose` / `-v` Flag
Running with `--verbose` (or `-v`) activates detailed diagnostic tracing:
- Displays per-case transaction attributes (`TransactionAmt`, `id_15`, `id_23`, `addr1`, `card1`).
- Traces the 8-stage LangGraph workflow execution with step-by-step state transitions.
- Logs retrieved historical closed cases from vector memory with cosine similarity scores.
- Prints the exact evidence scores (Card History, Shared Device, Proxy, Region Anomalies, Velocity Bursts).
- Displays pre-evidence and post-evidence Next Best Action (NBA) shifts and approval routes.
- Outputs FinCEN-compliant Suspicious Activity Report (SAR) filings when triggered.

Outputs are saved directly to `cases/HHG-001.json` through `cases/HHG-020.json`.

Validate submission compliance at any time:
```bash
python scripts/validate_cases.py
```

### 6. Launch the Platform & Dashboard

**Using One-Click Batch Script:**
```cmd
..\start_agent.bat
```
*(Or from within `fraud-investigation-agent`: `python server.py`)*

Open your browser to:
```
http://localhost:8000
```
The server automatically exposes:
- **Vision UI Dashboard**: `http://localhost:8000`
- **Dynamic Case Dossiers API**: `http://localhost:8000/api/cases`
- **Interactive Investigation API**: `http://localhost:8000/api/investigate`
- **System Health API**: `http://localhost:8000/api/status`

---

## 🗂️ Directory Structure

```
Bank-fraud-detection/
├── cases/                           # ★ 20 Validated Submission Answer Files
│   ├── HHG-001.json ... HHG-020.json
│   └── validate_submission.py       # Submission validator script
├── start_agent.bat                  # One-click platform launcher
├── stop_agent.bat                   # Platform shutdown script
└── fraud-investigation-agent/
    ├── frontend/                    # ★ Vision UI Web Dashboard
    │   ├── index.html               #   Single-page app shell + sidebar
    │   ├── styles.css               #   Glassmorphism design system
    │   ├── app.js                   #   Client-side routing + live API client
    │   └── assets/                  #   Branding and iconography
    ├── config/
    │   ├── settings.py              #   Central configuration (DATA_DIR, STRICT_GRAPH, OFFLINE_DEV)
    │   └── fraud_policies.json      #   Typologies, NBA matrix, SAR thresholds
    ├── data_real/                   # ★ Authentic Datasets (.gitignore'd)
    │   ├── transactions.csv         #   Full transaction register
    │   ├── identity.csv             #   Device identity records
    │   ├── closed_cases_history.csv #   Historical investigation outcomes
    │   └── case_pack.csv            #   20 exam cases
    ├── scripts/
    │   └── check_setup.py           # ★ Pre-flight environment & graph diagnostics
    ├── gsql/
    │   ├── schema.gsql              #   TigerGraph schema (8 vertex types, 9 edge types)
    │   ├── queries/                 #   GSQL graph algorithms
    │   └── setup_graph.sh           #   Schema bootstrap script
    ├── graph/
    │   ├── tigergraph_client.py     #   pyTigerGraph connector with STRICT_GRAPH enforcement
    │   └── mcp_server.py            #   FastAPI MCP adapter (port 8765)
    ├── rag/
    │   ├── graph_rag.py             #   Hybrid retrieval: GSQL + ChromaDB
    │   └── memory_store.py          #   Vector memory loaded from closed_cases_history.csv
    ├── agent/
    │   ├── state.py                 #   Pydantic models + LangGraph state definitions
    │   ├── workflow.py              #   8-stage LangGraph state machine (data-driven scoring)
    │   ├── tools.py                 #   External action tools (MFA, outreach, card freeze)
    │   ├── policy_engine.py         #   Next Best Action matrix & SAR determination
    │   └── sar_generator.py         #   FinCEN-compliant SAR narrative generator
    ├── eval/
    │   └── run_benchmark.py         #   Automated 20-case evaluation runner (--verbose flag)
    ├── server.py                    #   FastAPI application server (UI + API proxy)
    ├── .env                         #   Active environment secrets (never committed)
    ├── .env.example                 #   Environment variable template
    ├── requirements.txt
    └── README.md
```

---

## 🔌 TigerGraph Modes & Connection

The system supports strict live connectivity with intelligent diagnostic fallback control:

### Settings (`config/settings.py` / `.env`)
| Variable | Default | Purpose |
|---|---|---|
| `STRICT_GRAPH` | `true` | When true, enforces strict graph database integration. |
| `TG_TGCLOUD` | `true` | Enables TigerGraph Cloud SSL / HTTPS connectivity. |
| `TG_SSL_PORT` | `443` | SSL port for TigerGraph Cloud instances. |
| `OFFLINE_DEV` | `false` | When false, prevents silent mock fallback and raises a clear `ConnectionError` if TigerGraph is unreachable. When true, enables local dataset queries with loud warning headers. |

### Connection Troubleshooting
If `check_setup.py` or `tigergraph_client.py` reports a connection failure:
1. **Workspace Awake?** Log in to [TigerGraph Cloud](https://tgcloud.io/) and ensure your instance status is **Ready** (not *Paused* or *Stopped*).
2. **Host URL:** Check that `TG_HOST` includes `https://` (e.g. `https://tg-yourid.i.tgcloud.io`).
3. **SSL Port:** Verify `TG_SSL_PORT=443` and `TG_TGCLOUD=true`.
4. **Secret / Token:** Confirm `TG_SECRET` was created under *Admin Portal → Users & Roles → Secrets* with graph access rights.

---

## 🧠 Agent Lifecycle (8 Stages)

```
[Trigger] ──> [Investigate Subgraph] ──> [Gather GraphRAG Evidence]
    ──> [Assess Risk & Uncertainty]
         ├── uncertainty > 40% ──> [Extra Evidence: Step-Up MFA / Outreach] ──> (loop back)
         └── threshold met ──> [Post-Evidence NBA Decision]
                                ──> [SAR & Explainability]
                                ──> [Update Case Memory in Graph]
```

---

## 📊 Authentic Benchmark Output Format

Each of the 20 cases (`cases/HHG-001.json` ... `cases/HHG-020.json`) conforms exactly to the competition specification:

```json
{
  "case": {
    "case_id": "HHG-010",
    "customer_id": "C09292-P4",
    "account_id": "C09292-P4",
    "status": "closed",
    "verdict": "FRAUD",
    "pattern": "card_not_present_new_device",
    "fraud_probability": 0.88,
    "confidence": 0.88,
    "total_exposure": 1000.03,
    "affected_transactions": [3428986],
    "connected_cards": ["card1_12544"],
    "evidence": [
      { "signal": "new_device", "value": "New device profile (id_15=New, id_23=IP_PROXY)" },
      { "signal": "closed_case_similarity", "value": "Matched past fraud case CC-03310 (similarity 0.89)" }
    ],
    "retrieved_closed_cases": [
      { "case_id": "CC-03310", "similarity": 0.89, "pattern": "card_not_present_new_device" }
    ]
  },
  "sar_filing": {
    "sar_id": "SAR-HHG-010",
    "subject": "FinCEN Suspicious Activity Report — HHG-010",
    "filing_required": true,
    "amount": 1000.03,
    "narrative": "SUSPICIOUS ACTIVITY REPORT\n\nSUBJECT IDENTIFICATION: C09292-P4\nSUMMARY OF SUSPICIOUS ACTIVITY: Transaction 3428986 for $1,000.03 originated from a newly recognized device with high-risk proxy masking..."
  },
  "next_best_action": {
    "pre_evidence": {
      "action": "STEP_UP_AUTH",
      "approval_required": "auto",
      "reason": "Uncertainty elevated (45%); requesting customer step-up verification."
    },
    "post_evidence": {
      "action": "BLOCK_TRANSACTION",
      "approval_required": "L2",
      "reason": "Customer denied transaction authorization; critical proxy risk detected."
    }
  },
  "audit_trail": [
    { "stage": "trigger", "action": "Trigger ingested: risk_score 0.92" },
    { "stage": "gather_evidence", "action": "Retrieved 1-hop subgraph: 1 device, 1 card" },
    { "stage": "sar_and_explainability", "action": "SAR filed: threshold $1,000 exceeded" }
  ]
}
```

---

## 🔧 Tech Stack

| Layer         | Technology                                |
|---------------|-------------------------------------------|
| Graph DB      | TigerGraph Cloud (GSQL, WCC, PageRank)    |
| Agent         | LangGraph 0.2+ / Python 3.11              |
| LLM           | Groq (LiteLLM) — llama-4-scout / qwen3   |
| Vector Store  | ChromaDB (Historical Case Memory)         |
| GraphRAG      | GSQL Subgraph + ChromaDB Cosine Embeddings|
| MCP Adapter   | FastAPI + uvicorn                         |
| **Dashboard** | **Vision UI — HTML / CSS / JS (primary)** |
| API Server    | FastAPI (`server.py`)                     |
| Dataset       | IEEE-CIS Fraud Detection (Authentic Vesta)|

---

## 📝 License

Built for HHGOA Hackathon 2026. MIT License.
