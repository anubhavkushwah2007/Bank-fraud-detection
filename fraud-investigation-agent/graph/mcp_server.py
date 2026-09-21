"""
graph/mcp_server.py
───────────────────
FastAPI-based MCP (Model Context Protocol) tool adapter.
Exposes TigerGraph algorithms and GSQL queries as
standardised HTTP tool endpoints consumable by LangGraph agents.

Run: uvicorn graph.mcp_server:app --host 0.0.0.0 --port 8765
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from graph.tigergraph_client import get_graph_client

logger = logging.getLogger(__name__)
app = FastAPI(
    title="HHGOA TigerGraph MCP Server",
    description="Model Context Protocol adapter for TigerGraph fraud detection algorithms",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response Models ────────────────────────────────────────────────

class SharedEntitiesRequest(BaseModel):
    account_id:  str
    window_days: int = 30

class VelocityRequest(BaseModel):
    account_id:     str
    lookback_hours: int = 72

class FraudRingRequest(BaseModel):
    min_ring_risk: float = 0.60
    min_ring_size: int   = 3

class SimilarCasesRequest(BaseModel):
    typology:    str
    risk:        float
    top_k:       int = 5

class SubgraphRequest(BaseModel):
    account_id: str
    hop:        int = 2

class UpsertCaseRequest(BaseModel):
    case_id:   str
    case_data: Dict[str, Any]

class MCPToolResponse(BaseModel):
    tool:   str
    status: str  # SUCCESS | ERROR
    data:   Dict[str, Any]
    error:  Optional[str] = None


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "HHGOA TigerGraph MCP"}


@app.get("/tools")
async def list_tools() -> Dict[str, Any]:
    """List all available MCP tools with their schemas."""
    return {
        "tools": [
            {"name": "detect_shared_entities",  "description": "Find accounts sharing Card/Device/IP with target account within sliding window"},
            {"name": "trace_fund_velocity",      "description": "Compute transaction velocity, burst score, and fan-out ratios"},
            {"name": "graph_fraud_ring_detection","description": "Run WCC to detect fraud rings via shared identity"},
            {"name": "find_similar_cases",       "description": "Vector/attribute similarity search over resolved case history"},
            {"name": "get_subgraph",             "description": "Extract n-hop neighborhood subgraph around an account"},
            {"name": "upsert_case",              "description": "Persist or update a case record in TigerGraph"},
        ]
    }


@app.post("/tools/detect_shared_entities", response_model=MCPToolResponse)
async def detect_shared_entities(req: SharedEntitiesRequest) -> MCPToolResponse:
    """Detect accounts sharing Card, Device, or IP with the target account."""
    try:
        client = get_graph_client()
        result = client.detect_shared_entities(req.account_id, req.window_days)
        return MCPToolResponse(
            tool="detect_shared_entities",
            status="SUCCESS",
            data=result,
        )
    except Exception as e:
        logger.error(f"detect_shared_entities error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tools/trace_fund_velocity", response_model=MCPToolResponse)
async def trace_fund_velocity(req: VelocityRequest) -> MCPToolResponse:
    """Compute transaction velocity and burst score."""
    try:
        client = get_graph_client()
        result = client.trace_velocity(req.account_id, req.lookback_hours)
        return MCPToolResponse(
            tool="trace_fund_velocity",
            status="SUCCESS",
            data=result,
        )
    except Exception as e:
        logger.error(f"trace_fund_velocity error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tools/graph_fraud_ring_detection", response_model=MCPToolResponse)
async def graph_fraud_ring_detection(req: FraudRingRequest) -> MCPToolResponse:
    """Run WCC to detect fraud rings."""
    try:
        client = get_graph_client()
        result = client.detect_fraud_rings()
        return MCPToolResponse(
            tool="graph_fraud_ring_detection",
            status="SUCCESS",
            data=result,
        )
    except Exception as e:
        logger.error(f"graph_fraud_ring_detection error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tools/find_similar_cases", response_model=MCPToolResponse)
async def find_similar_cases(req: SimilarCasesRequest) -> MCPToolResponse:
    """Find similar historical cases by typology and risk score."""
    try:
        client = get_graph_client()
        result = client.find_similar_cases(req.typology, req.risk, req.top_k)
        return MCPToolResponse(
            tool="find_similar_cases",
            status="SUCCESS",
            data={"similar_cases": result},
        )
    except Exception as e:
        logger.error(f"find_similar_cases error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tools/get_subgraph", response_model=MCPToolResponse)
async def get_subgraph(req: SubgraphRequest) -> MCPToolResponse:
    """Extract n-hop neighborhood subgraph around an account."""
    try:
        client = get_graph_client()
        result = client.get_subgraph(req.account_id, req.hop)
        return MCPToolResponse(
            tool="get_subgraph",
            status="SUCCESS",
            data=result,
        )
    except Exception as e:
        logger.error(f"get_subgraph error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tools/upsert_case", response_model=MCPToolResponse)
async def upsert_case(req: UpsertCaseRequest) -> MCPToolResponse:
    """Persist or update a case record in TigerGraph."""
    try:
        client = get_graph_client()
        ok = client.upsert_case(req.case_id, req.case_data)
        return MCPToolResponse(
            tool="upsert_case",
            status="SUCCESS" if ok else "ERROR",
            data={"case_id": req.case_id, "persisted": ok},
        )
    except Exception as e:
        logger.error(f"upsert_case error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    from config import settings
    uvicorn.run("graph.mcp_server:app",
                host=settings.MCP_SERVER_HOST,
                port=settings.MCP_SERVER_PORT,
                reload=True)
