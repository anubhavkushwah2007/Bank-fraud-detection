"""
scripts/extend_schema.py
────────────────────────
Adds the `Cases` vertex type and its edges to the EXISTING live TigerGraph
graph (Transaction_Fraud) via a schema change job.
"""
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

import pyTigerGraph as tg

host     = os.getenv("TG_HOST", os.getenv("TIGERGRAPH_HOST", ""))
graph    = os.getenv("TG_GRAPHNAME", os.getenv("TG_GRAPH_NAME", "Transaction_Fraud"))
username = os.getenv("TG_USERNAME", os.getenv("TIGERGRAPH_USERNAME", "tigergraph"))
password = os.getenv("TG_PASSWORD", os.getenv("TIGERGRAPH_PASSWORD", "tigergraph"))
secret   = os.getenv("TG_SECRET", os.getenv("TIGERGRAPH_SECRET", ""))

if not host.startswith("http"):
    host = f"https://{host}"

print(f"Connecting to {host} graph={graph} ...")
conn = tg.TigerGraphConnection(
    host=host,
    graphname=graph,
    username=username,
    password=password,
    gsqlSecret=secret,
    tgCloud=True,
    sslPort=443,
)
ver = conn.getVer()
print(f"Connected — TigerGraph {ver}")

vtypes = conn.getVertexTypes()
if "Cases" in vtypes:
    cnt = conn.getVertexCount("Cases")
    print(f"✔ 'Cases' vertex type already exists in graph (current count: {cnt})")
    sys.exit(0)

# ── Schema change job to add Cases vertex + edges ────────────────────────────
job_gsql = f"""
USE GRAPH {graph}

CREATE SCHEMA_CHANGE JOB add_cases_schema FOR GRAPH {graph} {{
    ADD VERTEX Cases (
        PRIMARY_ID case_id STRING,
        status STRING DEFAULT "OPEN",
        verdict STRING DEFAULT "UNDECIDED",
        fraud_probability FLOAT DEFAULT 0.0,
        pattern STRING DEFAULT "",
        exposure_usd FLOAT DEFAULT 0.0,
        summary STRING DEFAULT "",
        opened_at STRING DEFAULT "",
        updated_at STRING DEFAULT "",
        customer_id STRING DEFAULT "",
        card_id STRING DEFAULT "",
        sar_required BOOL,
        sar_draft STRING DEFAULT ""
    );

    ADD DIRECTED EDGE CASE_INVOLVES (FROM Cases, TO Payment_Transaction) WITH REVERSE_EDGE="reverse_CASE_INVOLVES";
    ADD DIRECTED EDGE CASE_ON_CARD (FROM Cases, TO Card) WITH REVERSE_EDGE="reverse_CASE_ON_CARD";
    ADD UNDIRECTED EDGE CASE_SIMILAR_CASE (FROM Cases, TO Cases, similarity FLOAT DEFAULT 0.0);
}}
RUN SCHEMA_CHANGE JOB add_cases_schema
DROP JOB add_cases_schema
"""

print("\nRunning GSQL schema change job ...")
try:
    result = conn.gsql(job_gsql)
    print(result)
except Exception as e:
    print(f"GSQL result/error: {e}")

# Verify Cases vertex type now exists
print("\nVerifying schema ...")
vtypes = conn.getVertexTypes()
if "Cases" in vtypes:
    counts = conn.getVertexCount("Cases")
    print(f"✔ 'Cases' vertex type exists — current count: {counts}")
else:
    print("❌ 'Cases' vertex not found in vertex types.")
    sys.exit(1)

print("\n✅ Schema extension complete.")
