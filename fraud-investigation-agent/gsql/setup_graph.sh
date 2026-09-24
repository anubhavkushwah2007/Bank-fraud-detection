#!/usr/bin/env bash
# =============================================================
# setup_graph.sh — Bootstrap TigerGraph Schema & GSQL Queries
# Usage: bash gsql/setup_graph.sh
# Notes: Uses TG_GRAPHNAME / TG_GRAPH_NAME without dropping graphs
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Load .env if present
if [ -f "${BASE_DIR}/.env" ]; then
    set -a
    source "${BASE_DIR}/.env"
    set +a
fi

GRAPH_NAME="${TG_GRAPHNAME:-${TG_GRAPH_NAME:-${TIGERGRAPH_GRAPH:-Transaction_Fraud}}}"
TG_HOST="${TG_HOST:-${TIGERGRAPH_HOST:-localhost}}"
TG_USER="${TG_USERNAME:-${TIGERGRAPH_USERNAME:-tigergraph}}"
TG_PASS="${TG_PASSWORD:-${TIGERGRAPH_PASSWORD:-tigergraph}}"
TG_SECRET="${TG_SECRET:-${TIGERGRAPH_SECRET:-}}"

echo "============================================================"
echo "  HHGOA Real Fraud Graph — TigerGraph Bootstrap"
echo "  Host:  ${TG_HOST}"
echo "  Graph: ${GRAPH_NAME}"
echo "============================================================"

# Helper: run GSQL command
run_gsql_cmd() {
    local cmd="$1"
    if [ -n "${TG_SECRET}" ]; then
        gsql -s "${TG_SECRET}" "${cmd}"
    elif [ -n "${TG_PASS}" ]; then
        gsql -u "${TG_USER}" -p "${TG_PASS}" "${cmd}"
    else
        gsql "${cmd}"
    fi
}

# Helper: run GSQL file
run_gsql_file() {
    local file="$1"
    echo "  → Running: $(basename "${file}")"
    if [ -n "${TG_SECRET}" ]; then
        gsql -s "${TG_SECRET}" "${file}"
    elif [ -n "${TG_PASS}" ]; then
        gsql -u "${TG_USER}" -p "${TG_PASS}" "${file}"
    else
        gsql "${file}"
    fi
}

echo ""
echo "[1/3] Ensuring Graph exists: ${GRAPH_NAME}..."
run_gsql_cmd "CREATE GRAPH ${GRAPH_NAME}()" || true

echo ""
echo "[2/3] Applying Schema..."
TMP_SCHEMA="$(mktemp)"
echo "USE GRAPH ${GRAPH_NAME}" > "${TMP_SCHEMA}"
cat "${SCRIPT_DIR}/schema.gsql" >> "${TMP_SCHEMA}"
run_gsql_file "${TMP_SCHEMA}"
rm -f "${TMP_SCHEMA}"

echo ""
echo "[3/3] Compiling and Installing Queries..."
QUERIES=(
    "${SCRIPT_DIR}/queries/card_window.gsql"
    "${SCRIPT_DIR}/queries/device_neighbors.gsql"
    "${SCRIPT_DIR}/queries/region_neighbors.gsql"
    "${SCRIPT_DIR}/queries/shared_email_neighbors.gsql"
    "${SCRIPT_DIR}/queries/customer_history.gsql"
    "${SCRIPT_DIR}/queries/similar_closed_cases.gsql"
)

for q in "${QUERIES[@]}"; do
    if [ -f "${q}" ]; then
        echo "  → Compiling: $(basename "${q}")"
        TMP_Q="$(mktemp)"
        echo "USE GRAPH ${GRAPH_NAME}" > "${TMP_Q}"
        cat "${q}" >> "${TMP_Q}"
        run_gsql_file "${TMP_Q}"
        rm -f "${TMP_Q}"
    fi
done

echo "  → Installing all queries on ${GRAPH_NAME}..."
run_gsql_cmd "USE GRAPH ${GRAPH_NAME}; INSTALL QUERY card_window, device_neighbors, region_neighbors, shared_email_neighbors, customer_history, similar_closed_cases;"

echo ""
echo "✅ Schema and queries bootstrap complete!"
echo "   Next: python data/load_all.py"
