#!/usr/bin/env bash
# =============================================================
# setup_graph.sh  — Bootstrap TigerGraph FraudGraph
# Usage: bash gsql/setup_graph.sh
# Requires: GSQL CLI on PATH (TigerGraph installation)
# =============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRAPH_NAME="FraudGraph"
TG_HOST="${TIGERGRAPH_HOST:-localhost}"
TG_USER="${TIGERGRAPH_USERNAME:-tigergraph}"
TG_PASS="${TIGERGRAPH_PASSWORD:-tigergraph}"

echo "============================================================"
echo "  HHGOA Fraud Graph — TigerGraph Bootstrap"
echo "  Host: ${TG_HOST}   Graph: ${GRAPH_NAME}"
echo "============================================================"

# ── Helper: run a GSQL file ────────────────────────────────────────────────────
run_gsql() {
    local file="$1"
    echo "  → Running: $(basename "${file}")"
    gsql -u "${TG_USER}" -p "${TG_PASS}" -f "${file}"
}

# ── 1. Create Graph & Schema ───────────────────────────────────────────────────
echo ""
echo "[1/4] Creating graph schema..."
run_gsql "${SCRIPT_DIR}/schema.gsql"

# ── 2. Compile GSQL Queries ───────────────────────────────────────────────────
echo ""
echo "[2/4] Compiling GSQL queries..."
for qfile in "${SCRIPT_DIR}/queries/"*.gsql; do
    run_gsql "${qfile}"
done

# ── 3. Seed Fraud Patterns ────────────────────────────────────────────────────
echo ""
echo "[3/4] Seeding Fraud_Pattern vertices..."
gsql -u "${TG_USER}" -p "${TG_PASS}" << 'EOF'
USE GRAPH FraudGraph

BEGIN
UPSERT VERTEX Fraud_Pattern VALUES("TYP-001", "Card-Not-Present Fraud Ring",
  "Organized rings testing stolen card credentials", '["multiple_accounts_same_device","rapid_cross_merchant_testing"]',
  "Account -> Device <- Account", "FinCEN FIN-2012-A010", true)

UPSERT VERTEX Fraud_Pattern VALUES("TYP-002", "Account Takeover (ATO)",
  "Unauthorized access via credential stuffing or phishing", '["new_device_first_transaction","ip_country_mismatch"]',
  "Account -> NewDevice AND IP_Address (foreign)", "FFIEC IT 2023", true)

UPSERT VERTEX Fraud_Pattern VALUES("TYP-003", "Bust-Out Fraud",
  "Fraudster builds credit then maxes out", '["sudden_credit_limit_usage","address_change_prior_30_days"]',
  "Account -> high_value_transactions BURST within 48h", "FinCEN FIN-2015-A001", true)

UPSERT VERTEX Fraud_Pattern VALUES("TYP-004", "Synthetic Identity Fraud",
  "Fictitious identity from combined real PII fragments", '["ssn_dob_mismatch","shared_device_across_unrelated_accounts"]',
  "WCC: >5 Accounts sharing Device AND IP", "FTC 2022", true)

UPSERT VERTEX Fraud_Pattern VALUES("TYP-005", "Smurfing / Structuring",
  "Breaking large transfers below CTR thresholds", '["transactions_just_below_ctr_limit","high_fan_out_ratio"]',
  "Account -> [10+ Transactions <$10k] -> multiple Accounts", "31 U.S.C. 5324", true)
END

EOF

# ── 4. Verify installation ────────────────────────────────────────────────────
echo ""
echo "[4/4] Verifying installation..."
gsql -u "${TG_USER}" -p "${TG_PASS}" "USE GRAPH ${GRAPH_NAME}; SHOW VERTEX *; SHOW EDGE *; SHOW QUERY *;"

echo ""
echo "✅  FraudGraph bootstrap complete!"
echo "    Run data ingestion next: python data/ingest_ieee.py"
