"""
scripts/check_setup.py
──────────────────────
Diagnostic setup verification tool for the HHGOA Fraud Investigation Agent.

Verifies:
1. Environment variables in .env (TG_HOST, TG_GRAPH_NAME, TG_SECRET, LLM keys)
2. Four authentic CSV files exist in DATA_DIR (transactions.csv, identity.csv,
   closed_cases_history.csv, case_pack.csv)
3. TigerGraph instance is reachable and authenticated, and prints vertex counts per type.

Exit Code:
  0 on success
  1 on any failure
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import settings


def check_env_vars() -> bool:
    """Verify required environment variables are set."""
    print("\n[1/3] Checking Environment Configuration (.env)...")
    required = [
        ("TG_HOST / TIGERGRAPH_HOST", settings.TIGERGRAPH_HOST),
        ("TG_GRAPH_NAME / TIGERGRAPH_GRAPH", settings.TIGERGRAPH_GRAPH),
        ("TG_SECRET / TIGERGRAPH_SECRET", settings.TIGERGRAPH_SECRET or settings.TIGERGRAPH_PASSWORD),
        ("LLM_PROVIDER", settings.LLM_PROVIDER),
    ]

    missing = []
    for name, val in required:
        if not val or val in ("http://localhost", ""):
            print(f"  ❌ {name:<35}: NOT CONFIGURED / DEFAULT")
            missing.append(name)
        else:
            masked = str(val)[:12] + "..." if len(str(val)) > 15 else str(val)
            print(f"  ✔ {name:<35}: {masked}")

    # Check LLM key
    llm_key = settings.GROQ_API_KEY if settings.LLM_PROVIDER == "groq" else (settings.GOOGLE_API_KEY or settings.OPENAI_API_KEY)
    if not llm_key:
        print(f"  ❌ {'LLM API KEY (' + settings.LLM_PROVIDER + ')':<35}: MISSING")
        missing.append(f"{settings.LLM_PROVIDER.upper()}_API_KEY")
    else:
        print(f"  ✔ {'LLM API KEY (' + settings.LLM_PROVIDER + ')':<35}: {llm_key[:6]}...{llm_key[-4:]}")

    print(f"  ℹ OFFLINE_DEV                       : {settings.OFFLINE_DEV}")
    print(f"  ℹ STRICT_GRAPH                      : {settings.STRICT_GRAPH}")
    print(f"  ℹ TG_TGCLOUD                        : {settings.TG_TGCLOUD}")
    print(f"  ℹ TG_SSL_PORT                       : {settings.TG_SSL_PORT}")

    if missing:
        print(f"\n❌ Environment check FAILED. Missing or unset: {', '.join(missing)}")
        return False
    print("✔ Environment variables OK.")
    return True


def check_csv_files() -> bool:
    """Verify the four authentic CSV files exist in DATA_DIR."""
    print(f"\n[2/3] Checking Authentic CSV Datasets in {settings.DATA_DIR}...")
    if not settings.DATA_DIR.exists():
        print(f"  ❌ DATA_DIR '{settings.DATA_DIR}' does not exist!")
        return False

    csv_targets = [
        ("Transactions CSV", settings.TRANSACTIONS_CSV),
        ("Identity CSV", settings.IDENTITY_CSV),
        ("Closed Cases History CSV", settings.CLOSED_CASES_CSV),
        ("Case Pack CSV", settings.CASE_PACK_CSV),
    ]

    all_exist = True
    for label, path in csv_targets:
        if path.exists() and path.is_file():
            size_mb = path.stat().st_size / (1024 * 1024)
            print(f"  ✔ {label:<26}: {path.name:<25} ({size_mb:>8.2f} MB)")
        else:
            print(f"  ❌ {label:<26}: {path.name:<25} (NOT FOUND at {path})")
            all_exist = False

    if not all_exist:
        print("\n❌ CSV file check FAILED. Ensure all 4 real dataset files are located in DATA_DIR.")
        return False
    print("✔ All 4 CSV files present.")
    return True


def check_tigergraph_connection() -> bool:
    """Verify live TigerGraph reachability, authentication, and print vertex counts."""
    print("\n[3/3] Checking TigerGraph Database Reachability & Authentication...")
    try:
        import pyTigerGraph as tg
    except ImportError:
        print("  ❌ pyTigerGraph package is not installed. Run: pip install pyTigerGraph")
        return False

    host = settings.TIGERGRAPH_HOST
    if not host.startswith("http://") and not host.startswith("https://"):
        host = f"https://{host}"

    try:
        conn = tg.TigerGraphConnection(
            host=host,
            graphname=settings.TIGERGRAPH_GRAPH,
            username=settings.TIGERGRAPH_USERNAME,
            password=settings.TIGERGRAPH_PASSWORD,
            gsqlSecret=settings.TIGERGRAPH_SECRET,
            tgCloud=settings.TG_TGCLOUD,
            sslPort=settings.TG_SSL_PORT,
        )

        version = conn.getVer()
        print(f"  ✔ Connected to TigerGraph: {host} (Server v{version})")
        print(f"  ✔ Authenticated on graph: '{settings.TIGERGRAPH_GRAPH}'")

        # Query vertex types and counts
        vtypes = conn.getVertexTypes()
        if not vtypes:
            print("  ⚠️ Warning: Connected to graph, but no vertex types defined in schema.")
            return True

        print("\n  Graph Vertex Counts per Type:")
        print("  " + "─" * 45)
        total_vertices = 0
        for vt in sorted(vtypes):
            try:
                cnt = conn.getVertexCount(vt)
                total_vertices += cnt
                print(f"    • {vt:<22} : {cnt:>12,}")
            except Exception as e:
                print(f"    • {vt:<22} : (Error reading count: {e})")
        print("  " + "─" * 45)
        print(f"    Total Vertices       : {total_vertices:>12,}\n")
        return True

    except Exception as e:
        print(f"\n  ❌ Connection to TigerGraph FAILED:")
        print(f"     {e}")
        print("\n  Troubleshooting Checklist:")
        print(f"  1. Is your TigerGraph Cloud / Savanna workspace running (not stopped/sleeping)?")
        print(f"  2. Does TG_HOST have the correct URL scheme (e.g. 'https://tg-xxxx.tgcloud.io')?")
        print(f"  3. Is TG_SECRET (or GSQL secret) valid and generated on graph '{settings.TIGERGRAPH_GRAPH}'?")
        print(f"  4. Are TG_USERNAME and TG_PASSWORD correct?")
        print(f"  5. Note: If developing offline without live graph, set OFFLINE_DEV=true.")
        return False


def main():
    print("=" * 70)
    print("  HHGOA FRAUD INVESTIGATION AGENT — SETUP VERIFICATION")
    print("=" * 70)

    ok_env = check_env_vars()
    ok_csv = check_csv_files()
    ok_tg  = check_tigergraph_connection()

    print("=" * 70)
    if ok_env and ok_csv and ok_tg:
        print("🎉 ALL CHECKS PASSED: Environment, CSV datasets, and live TigerGraph are READY!\n")
        sys.exit(0)
    else:
        print("❌ SETUP VERIFICATION FAILED: Resolve the items marked ❌ above.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
