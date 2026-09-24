"""
server.py
─────────
Unified FastAPI server that:
  1. Serves the frontend static files (HTML/CSS/JS) at /
  2. Exposes REST API endpoints at /api/ for real investigations
  3. Proxies to the TigerGraph MCP tools
  4. Reports live system status (mode, graph, LLM, RAG)

Run:  python server.py          (or: uvicorn server:app --host 0.0.0.0 --port 8000 --reload)
Open: http://localhost:8000
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure project root is on sys.path so imports like 'config.settings' resolve
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings

logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL if hasattr(settings, "LOG_LEVEL") else "INFO", logging.INFO))
logger = logging.getLogger("hhgoa.server")

# ── FastAPI App ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="HHGOA Fraud Investigation Platform",
    description="Unified backend serving the Vision UI dashboard + agent API + MCP proxy",
    version="2.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# API: System Status
# ══════════════════════════════════════════════════════════════════════════════

def _check_tigergraph() -> Dict[str, Any]:
    """Probe TigerGraph connectivity and report real vertex counts."""
    try:
        from graph.tigergraph_client import get_graph_client
        client = get_graph_client()
        if client.conn is not None:
            counts = {}
            try:
                raw = client.conn.getVertexCount("*")
                if isinstance(raw, dict):
                    counts = raw
                elif isinstance(raw, (int, float)):
                    counts = {"Transaction": int(raw)}
            except Exception as e:
                logger.warning(f"Live vertex count '*' query failed: {e}")

            if not counts:
                try:
                    vtypes = client.conn.getVertexTypes()
                except Exception:
                    vtypes = ["Transaction", "Payment_Transaction", "Customer", "Card", "DeviceProfile", "EmailDomain", "BillingRegion", "ClosedCase", "Case", "Cases"]
                for vt in vtypes:
                    try:
                        cnt = client.conn.getVertexCount(vt)
                        if cnt is not None:
                            counts[vt] = int(cnt)
                    except Exception:
                        pass

            total_v = sum(counts.values()) if counts else 0
            return {
                "status": "live",
                "host": settings.TIGERGRAPH_HOST,
                "graph": settings.TIGERGRAPH_GRAPH,
                "records": total_v,
                "total_vertices": total_v,
                "vertex_counts": counts,
            }

        # Offline / dataset mode
        df = client._get_offline_df()
        if df is not None:
            from rag.memory_store import get_memory_store
            ms = get_memory_store()
            counts = {
                "Transaction": len(df),
                "Customer": int(df["customer_id"].nunique()) if "customer_id" in df.columns else 20,
                "ClosedCase": ms.count(),
                "Case": len(client._offline_cases),
            }
            total_v = sum(counts.values())
            return {
                "status": "offline_dev" if settings.OFFLINE_DEV else "dataset",
                "host": settings.TIGERGRAPH_HOST if not settings.OFFLINE_DEV else "local_dataset",
                "graph": settings.TIGERGRAPH_GRAPH,
                "records": total_v,
                "total_vertices": total_v,
                "vertex_counts": counts,
            }

        return {
            "status": "offline",
            "host": settings.TIGERGRAPH_HOST,
            "graph": settings.TIGERGRAPH_GRAPH,
            "records": 0,
            "vertex_counts": {},
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "records": 0, "vertex_counts": {}}


def _check_llm() -> Dict[str, Any]:
    """Check LLM client availability."""
    try:
        from agent.llm_client import get_rate_limited_llm
        llm = get_rate_limited_llm()
        return {
            "status": "ready" if llm._client else "no_client",
            "provider": settings.LLM_PROVIDER,
            "primary_model": llm.primary_model,
            "fallback_model": llm.fallback_model,
            "calls": llm.calls_count,
            "remaining": llm.calls_remaining,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _check_rag() -> Dict[str, Any]:
    """Check RAG / memory store."""
    try:
        from rag.memory_store import get_memory_store
        ms = get_memory_store()
        return {
            "status": "ready",
            "closed_cases": ms.count(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _check_mcp() -> Dict[str, Any]:
    """Check if the MCP server is reachable."""
    import urllib.request
    try:
        url = f"http://localhost:{settings.MCP_SERVER_PORT}/health"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            return {"status": "online", "port": settings.MCP_SERVER_PORT, **data}
    except Exception:
        return {"status": "offline", "port": settings.MCP_SERVER_PORT}


@app.get("/api/status")
async def system_status():
    """Return live system status for all components."""
    return {
        "mode": "offline_dev" if settings.OFFLINE_DEV else "live",
        "offline_dev": settings.OFFLINE_DEV,
        "strict_graph": settings.STRICT_GRAPH,
        "graph": _check_tigergraph(),
        "llm": _check_llm(),
        "rag": _check_rag(),
        "mcp": _check_mcp(),
        "timestamp": time.time(),
    }


# ══════════════════════════════════════════════════════════════════════════════
# API: Run Real Investigation
# ══════════════════════════════════════════════════════════════════════════════

class InvestigateRequest(BaseModel):
    case_id: Optional[str] = None
    account_id: Optional[str] = None
    transaction_id: Optional[str] = None
    trigger_type: str = "risk_score"
    initial_risk: float = 0.75
    amount: float = 5000.0


@app.post("/api/investigate")
async def run_investigation_api(req: InvestigateRequest):
    """Run a full 9-stage LangGraph investigation and return the result."""
    try:
        from agent.state import TriggerEvent, TriggerType
        from agent.workflow import run_investigation_sequential

        # Map trigger type string
        tt_map = {
            "risk_score": TriggerType.RISK_SCORE,
            "HIGH_RISK_SCORE": TriggerType.RISK_SCORE,
            "customer_report": TriggerType.CUSTOMER_REPORT,
            "CUSTOMER_REPORT": TriggerType.CUSTOMER_REPORT,
            "analyst_request": TriggerType.ANALYST_REQUEST,
            "ANALYST_REQUEST": TriggerType.ANALYST_REQUEST,
            "VELOCITY_SPIKE": TriggerType.RISK_SCORE,
            "PATTERN_MATCH": TriggerType.RISK_SCORE,
        }
        ttype = tt_map.get(req.trigger_type, TriggerType.RISK_SCORE)

        # Build trigger
        trigger = TriggerEvent(
            case_id=req.case_id or f"LIVE_{int(time.time())}",
            card_id=req.account_id or "ACC_000000",
            customer_id=req.account_id or "ACC_000000",
            flagged_txn_id=req.transaction_id or f"TXN_{int(time.time())}",
            trigger_type=ttype,
            risk_score=req.initial_risk,
            initial_risk=req.initial_risk,
        )

        result = run_investigation_sequential(trigger)
        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"Investigation failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# API: Benchmark — Run all 20 HHG cases
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/benchmark")
async def run_benchmark():
    """Run all 20 real cases from case_pack.csv through the agent and return results."""
    try:
        from eval.run_benchmark import load_all_cases, run_single_case
        all_cases = load_all_cases()
        results = []
        for c in all_cases:
            res = run_single_case(c)
            results.append(res)
        return JSONResponse(content={
            "total": len(results),
            "results": results,
        })
    except Exception as e:
        logger.error(f"Benchmark failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# API: MCP Proxy — Forward to TigerGraph tools
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/mcp/{tool_name}")
async def mcp_proxy(tool_name: str, request: Request):
    """Proxy calls to the graph client's MCP-compatible tools."""
    try:
        from graph.tigergraph_client import get_graph_client
        client = get_graph_client()
        body = await request.json()

        tool_map = {
            "detect_shared_entities": lambda b: client.detect_shared_entities(
                b.get("account_id", ""), b.get("device_profile")
            ),
            "trace_fund_velocity": lambda b: client.trace_velocity(
                b.get("account_id", ""), b.get("lookback_hours", 72)
            ),
            "graph_fraud_ring_detection": lambda b: client.detect_fraud_rings(),
            "find_similar_cases": lambda b: client.find_similar_cases(
                b.get("typology", ""), b.get("risk", 0.7), b.get("top_k", 5)
            ),
            "get_subgraph": lambda b: client.get_subgraph(
                b.get("account_id", ""), b.get("hop", 2)
            ),
        }

        if tool_name not in tool_map:
            raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")

        result = tool_map[tool_name](body)
        return {"tool": tool_name, "status": "SUCCESS", "data": result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MCP tool {tool_name} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# API: Cases data
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/cases")
async def get_cases():
    """Return the authentic 20 cases from the cases/ directory (the real answer files)."""
    cases_dir = settings.CASES_OUTPUT_DIR
    if not cases_dir.exists() or not list(cases_dir.glob("HHG-*.json")):
        cases_dir = PROJECT_ROOT.parent / "cases"

    case_files = sorted(cases_dir.glob("HHG-*.json"))
    if not case_files:
        raise HTTPException(status_code=404, detail=f"No answer files found in {cases_dir}")

    results = []
    for fp in case_files:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                raw = json.load(f)
            results.append(raw)
        except Exception as e:
            logger.warning(f"Error loading {fp.name}: {e}")
    return results


@app.get("/api/case/{case_id}")
async def get_single_case(case_id: str):
    """Return the full answer file for a specific case."""
    cid = case_id if case_id.endswith(".json") else f"{case_id}.json"
    cases_dir = settings.CASES_OUTPUT_DIR
    file_path = cases_dir / cid
    if not file_path.exists():
        file_path = PROJECT_ROOT.parent / "cases" / cid

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Case file {cid} not found")

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ══════════════════════════════════════════════════════════════════════════════
# Static Files — Serve Frontend
# ══════════════════════════════════════════════════════════════════════════════

FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Mount static files for CSS, JS, assets, and data sub-directories
app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
app.mount("/data", StaticFiles(directory=str(FRONTEND_DIR / "data")), name="data")


@app.get("/styles.css")
async def serve_css():
    return FileResponse(str(FRONTEND_DIR / "styles.css"), media_type="text/css", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/app.js")
async def serve_js():
    return FileResponse(str(FRONTEND_DIR / "app.js"), media_type="application/javascript", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/")
async def serve_index():
    """Serve index.html at root."""
    return FileResponse(str(FRONTEND_DIR / "index.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("FRONTEND_PORT", "8000"))
    logger.info(f"Starting HHGOA Platform on http://localhost:{port}")
    logger.info(f"  STRICT_GRAPH={settings.STRICT_GRAPH}  OFFLINE_DEV={settings.OFFLINE_DEV}")
    logger.info(f"  LLM_PROVIDER={settings.LLM_PROVIDER}  MODEL={settings.LLM_MODEL}")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
