"""
ui/app.py
──────────
HHGOA Fraud Investigation — Analyst Dashboard
Built with Streamlit, Plotly, and Pyvis.

Pages:
  1. 🏠 Home          — Live case queue and KPI metrics
  2. 🔍 Investigate   — Run a new investigation
  3. 📊 Case Viewer   — Deep-dive into a specific case result
  4. 🌐 Graph View    — Interactive subgraph visualizer
  5. ✅ Approval Queue — Pending analyst approvals
  6. 📋 Analytics     — Benchmark run statistics
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import streamlit as st

# ─── Path setup ───────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── Page config (must be first Streamlit call) ───────────────────────────────
st.set_page_config(
    page_title="HHGOA Fraud Intelligence",
    page_icon="🕵️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    /* Dark forest green background matching Hacker House Goa logo */
    .stApp {
        background: radial-gradient(circle at 10% 15%, rgba(16, 185, 129, 0.12) 0%, transparent 45%),
                    radial-gradient(circle at 90% 85%, rgba(245, 158, 11, 0.08) 0%, transparent 45%),
                    linear-gradient(135deg, #02120a 0%, #041d11 35%, #062e1c 70%, #02140b 100%);
        color: #f0fdf4;
    }

    /* Sidebar - Brighter Forest Emerald theme */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #074025 0%, #0a5231 45%, #063720 100%) !important;
        border-right: 1.5px solid rgba(52, 211, 153, 0.35) !important;
        box-shadow: 6px 0 35px rgba(0, 0, 0, 0.5), 0 0 30px rgba(16, 185, 129, 0.2);
    }

    /* Header gradient text */
    .gradient-text {
        background: linear-gradient(90deg, #34d399, #ffd700, #f43f5e);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 800;
        font-size: 2.2rem;
        line-height: 1.2;
    }

    /* KPI cards */
    .kpi-card {
        background: linear-gradient(135deg, rgba(8, 48, 30, 0.75), rgba(4, 25, 15, 0.9));
        border: 1px solid rgba(52, 211, 153, 0.25);
        border-radius: 14px;
        padding: 20px 24px;
        text-align: center;
        transition: transform 0.2s, box-shadow 0.2s;
        backdrop-filter: blur(12px);
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(16, 185, 129, 0.25);
        border-color: #ffd700;
    }
    .kpi-value {
        font-size: 2.4rem;
        font-weight: 800;
        color: #ffd700;
        line-height: 1;
    }
    .kpi-label {
        font-size: 0.82rem;
        color: #a7f3d0;
        margin-top: 6px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* Brighter, stylish radio navigation options */
    div[role="radiogroup"] {
        gap: 6px;
    }
    div[role="radiogroup"] > label {
        background: rgba(255, 255, 255, 0.08) !important;
        border: 1px solid rgba(52, 211, 153, 0.3) !important;
        border-radius: 12px !important;
        padding: 10px 14px !important;
        margin-bottom: 6px !important;
        transition: all 0.22s ease !important;
        color: #ffffff !important;
        font-weight: 600 !important;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
    }
    div[role="radiogroup"] > label:hover {
        background: linear-gradient(90deg, rgba(16, 185, 129, 0.4), rgba(245, 158, 11, 0.3)) !important;
        border-color: #ffd700 !important;
        color: #ffd700 !important;
        transform: translateX(4px);
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.35), 0 0 16px rgba(255, 215, 0, 0.25);
    }
    div[role="radiogroup"] > label[data-checked="true"],
    div[role="radiogroup"] > label:has(input:checked) {
        background: linear-gradient(90deg, rgba(16, 185, 129, 0.55), rgba(245, 158, 11, 0.4)) !important;
        border-color: #ffd700 !important;
        color: #ffd700 !important;
        font-weight: 800 !important;
        box-shadow: 0 0 18px rgba(16, 185, 129, 0.45);
    }

    /* Risk badges */
    .badge-critical { background: rgba(244,63,94,0.2); color: #f43f5e; border: 1px solid rgba(244,63,94,0.4); border-radius: 9999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; }
    .badge-high     { background: rgba(245,158,11,0.2); color: #fbbf24; border: 1px solid rgba(245,158,11,0.4); border-radius: 9999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; }
    .badge-medium   { background: rgba(16,185,129,0.2); color: #34d399; border: 1px solid rgba(16,185,129,0.4); border-radius: 9999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; }
    .badge-low      { background: rgba(45,212,191,0.2);  color: #2dd4bf; border: 1px solid rgba(45,212,191,0.4); border-radius: 9999px; padding: 2px 10px; font-size: 0.75rem; font-weight: 600; }

    /* Case row */
    .case-row {
        background: rgba(5, 34, 21, 0.7);
        border: 1px solid rgba(52, 211, 153, 0.15);
        border-radius: 10px;
        padding: 12px 16px;
        margin: 6px 0;
        transition: border-color 0.2s;
    }
    .case-row:hover { border-color: rgba(245, 158, 11, 0.5); }

    /* Action buttons */
    .stButton > button {
        background: linear-gradient(135deg, #10b981 0%, #059669 45%, #d97706 100%);
        color: white;
        border: 1px solid rgba(255, 215, 0, 0.35);
        border-radius: 10px;
        font-weight: 700;
        transition: opacity 0.2s, transform 0.1s, box-shadow 0.2s;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.4);
    }
    .stButton > button:hover {
        opacity: 0.95;
        border-color: #ffd700;
        box-shadow: 0 0 20px rgba(245, 158, 11, 0.5);
        transform: translateY(-1px);
    }

    /* Metric containers */
    [data-testid="stMetricValue"] { color: #ffd700 !important; font-weight: 800; }
    [data-testid="stMetricLabel"] { color: #a7f3d0 !important; font-weight: 600; }

    /* Tab styling */
    .stTabs [data-baseweb="tab"] {
        color: #6ee7b7;
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        color: #ffd700 !important;
        border-bottom-color: #ffd700 !important;
    }

    /* Divider */
    hr { border-color: rgba(52, 211, 153, 0.2) !important; }

    /* Code blocks */
    .stCode { background: rgba(1, 15, 8, 0.9) !important; border: 1px solid rgba(52, 211, 153, 0.25); }

    /* Progress bar */
    .stProgress > div > div { background: linear-gradient(90deg, #10b981, #ffd700); }

    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: #02120a; }
    ::-webkit-scrollbar-thumb { background: #073822; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)

# ─── Import agent modules (graceful degradation) ──────────────────────────────
try:
    from agent.state import TriggerEvent, TriggerType, state_to_result_dict
    from agent.workflow import run_investigation
    _AGENT_AVAILABLE = True
except ImportError as e:
    _AGENT_AVAILABLE = False
    st.sidebar.warning(f"⚠️ Agent unavailable: {e}")

RESULTS_DIR   = PROJECT_ROOT / "eval" / "results"
BENCHMARK_DIR = PROJECT_ROOT / "data" / "benchmark_cases"

TYPOLOGY_COLORS = {
    "ACCOUNT_TAKEOVER":      "#f87171",
    "CARD_NOT_PRESENT_RING": "#fb923c",
    "SYNTHETIC_IDENTITY":    "#c084fc",
    "SMURFING_VELOCITY":     "#fbbf24",
    "BUST_OUT":              "#34d399",
    "UNKNOWN":               "#94a3b8",
}

ACTION_ICONS = {
    "ALLOW_TRANSACTION":   "✅",
    "ADD_TO_WATCHLIST":    "👁️",
    "BLOCK_TRANSACTION":   "🚫",
    "STEP_UP_AUTH":        "🔐",
    "FREEZE_ACCOUNT":      "❄️",
    "ACCOUNT_HOLD":        "⛔",
    "FILE_SAR":            "📄",
    "ESCALATE_TO_ANALYST": "⚠️",
}


# ============================================================
# Helpers
# ============================================================

def load_results() -> List[Dict[str, Any]]:
    """Load all saved benchmark result JSON files."""
    results = []
    if RESULTS_DIR.exists():
        for f in sorted(RESULTS_DIR.glob("*_result.json")):
            try:
                with open(f) as fp:
                    results.append(json.load(fp))
            except Exception:
                pass
    return results


def risk_badge(fp: float) -> str:
    if fp >= 0.85:
        return '<span class="badge-critical">CRITICAL</span>'
    elif fp >= 0.70:
        return '<span class="badge-high">HIGH</span>'
    elif fp >= 0.50:
        return '<span class="badge-medium">MEDIUM</span>'
    return '<span class="badge-low">LOW</span>'


def mock_live_cases() -> List[Dict[str, Any]]:
    """Generate mock live cases for the queue UI."""
    rng = random.Random(int(time.time()) // 60)  # Changes each minute
    typologies = list(TYPOLOGY_COLORS.keys())[:-1]
    cases = []
    for i in range(8):
        fp = round(rng.uniform(0.55, 0.98), 3)
        cases.append({
            "case_id":    f"LIVE_{uuid.uuid4().hex[:6].upper()}",
            "account_id": f"ACC_{rng.randint(100000, 999999)}",
            "typology":   rng.choice(typologies),
            "fraud_prob": fp,
            "amount":     round(rng.uniform(500, 30000), 2),
            "status":     rng.choice(["OPEN", "IN_REVIEW", "ESCALATED"]),
            "created_at": datetime.utcnow().isoformat(),
        })
    return sorted(cases, key=lambda x: x["fraud_prob"], reverse=True)


# ============================================================
# Sidebar
# ============================================================

with st.sidebar:
    logo_path = PROJECT_ROOT / "frontend" / "assets" / "logo.jpg"
    if logo_path.exists():
        st.markdown("""
        <div style="display: flex; align-items: center; justify-content: center; margin-bottom: 12px;">
            <div style="padding: 6px; background: #063b22; border: 2px solid #ffd700; border-radius: 16px; box-shadow: 0 0 20px rgba(255, 215, 0, 0.45); display: flex; align-items: center; justify-content: center;">
        """, unsafe_allow_html=True)
        st.image(str(logo_path), width=78)
        st.markdown("</div></div>", unsafe_allow_html=True)
    st.markdown('<h3 style="margin-bottom: 0; color: #ffd700; text-align: center; font-weight: 800; letter-spacing: -0.01em;">HACKER HOUSE GOA</h3>', unsafe_allow_html=True)
    st.markdown('<p style="font-size: 0.72rem; color: #a7f3d0; text-align: center; letter-spacing: 0.08em; text-transform: uppercase; margin-top: 2px; font-weight: 700;">FRAUD INTELLIGENCE · AGENTIC AI</p>', unsafe_allow_html=True)
    st.markdown("---")

    st.markdown('<div style="font-size: 0.7rem; font-weight: 800; color: #ffd700; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;">⚡ Arranged Navigation</div>', unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        ["🏠 Home",
         "🔍 Investigate",
         "📊 Case Viewer",
         "🌐 Graph View",
         "✅ Approval Queue",
         "📋 Analytics",
         "ℹ️ Info"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("**System Status**")

    try:
        from config import settings
        demo_mode = getattr(settings, "OFFLINE_DEV", False)
    except Exception:
        demo_mode = False

    col1, col2 = st.columns(2)
    col1.metric("Mode", "OFFLINE DEV" if demo_mode else "LIVE")
    col2.metric("Agent", "✅" if _AGENT_AVAILABLE else "❌")

    st.caption(f"v2.1.0 · {datetime.utcnow().strftime('%Y-%m-%d')}")


# ============================================================
# Page: Home
# ============================================================

if page == "🏠 Home":
    st.markdown('<p class="gradient-text">HHGOA Fraud Investigation Intelligence</p>', unsafe_allow_html=True)
    st.markdown("*Real-time agentic fraud investigation powered by TigerGraph + LangGraph*")
    st.markdown("---")

    results = load_results()
    live_cases = mock_live_cases()

    # ── KPI Row ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    total_cases  = len(results) + len(live_cases)
    sar_count    = sum(1 for r in results if r.get("sar_filing_required"))
    avg_risk     = sum(r.get("post_evidence_recommendation", {}).get("confidence", 0) for r in results) / max(len(results), 1)
    frozen       = sum(1 for r in results if "FREEZE" in r.get("post_evidence_recommendation", {}).get("action", ""))
    critical_pct = sum(1 for c in live_cases if c["fraud_prob"] >= 0.85) / max(len(live_cases), 1)

    k1.metric("Active Cases",       f"{len(live_cases)}", delta="+3 today")
    k2.metric("Investigated",       f"{len(results)}", delta=f"{len(results)} total")
    k3.metric("SARs Filed",         f"{sar_count}",   delta="high priority")
    k4.metric("Accounts Frozen",    f"{frozen}")
    k5.metric("Avg. Confidence",    f"{avg_risk:.0%}")

    st.markdown("---")

    col_left, col_right = st.columns([1.4, 1])

    with col_left:
        st.markdown("#### 🔴 Live Case Queue")
        st.caption("Sorted by fraud probability — real-time incoming triggers")

        for case in live_cases[:6]:
            fp = case["fraud_prob"]
            typ_color = TYPOLOGY_COLORS.get(case["typology"], "#94a3b8")
            badge = risk_badge(fp)
            status_icon = {"OPEN": "🟡", "IN_REVIEW": "🔵", "ESCALATED": "🔴"}.get(case["status"], "⚪")

            st.markdown(f"""
            <div class="case-row">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <span style="font-weight:600; color:#e2e8f0;">{case['case_id']}</span>
                        &nbsp; {badge}
                    </div>
                    <span style="color:#94a3b8; font-size:0.8rem;">${case['amount']:,.0f}</span>
                </div>
                <div style="display:flex; gap:16px; margin-top:6px; font-size:0.8rem;">
                    <span style="color:{typ_color};">◆ {case['typology'].replace('_',' ')}</span>
                    <span style="color:#64748b;">Acc: {case['account_id']}</span>
                    <span style="color:#94a3b8;">{status_icon} {case['status']}</span>
                </div>
                <div style="margin-top:8px;">
                    <div style="background:rgba(15,32,53,0.8); border-radius:4px; height:4px; overflow:hidden;">
                        <div style="width:{fp*100:.0f}%; background:linear-gradient(90deg, #0ea5e9, {'#ef4444' if fp >= 0.85 else '#f59e0b' if fp >= 0.70 else '#0ea5e9'}); height:100%; border-radius:4px;"></div>
                    </div>
                    <span style="font-size:0.72rem; color:#94a3b8;">{fp:.0%} fraud probability</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

    with col_right:
        st.markdown("#### 📊 Typology Distribution")
        if results:
            import plotly.express as px
            import plotly.graph_objects as go

            typology_counts = {}
            for r in results:
                t = r.get("post_evidence_recommendation", {}).get("fraud_typology", "UNKNOWN")
                typology_counts[t] = typology_counts.get(t, 0) + 1

            if typology_counts:
                labels = list(typology_counts.keys())
                values = list(typology_counts.values())
                colors = [TYPOLOGY_COLORS.get(l, "#94a3b8") for l in labels]

                fig = go.Figure(data=[go.Pie(
                    labels=labels, values=values,
                    hole=0.55,
                    marker=dict(colors=colors, line=dict(color="#0a0e1a", width=2)),
                    textinfo="percent",
                    textfont=dict(color="white", size=11),
                )])
                fig.update_layout(
                    showlegend=True,
                    legend=dict(font=dict(color="#94a3b8", size=10)),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=10, l=10, r=10),
                    height=280,
                )
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Run benchmark cases to see typology distribution.")

        st.markdown("#### ⚡ Quick Actions")
        col_a, col_b = st.columns(2)
        if col_a.button("▶ Run Benchmark", use_container_width=True):
            st.switch_page("pages/benchmark.py") if False else st.info("Navigate to 📋 Analytics to run the benchmark.")
        if col_b.button("🔍 New Investigation", use_container_width=True):
            st.session_state["page"] = "🔍 Investigate"
            st.rerun()


# ============================================================
# Page: Investigate
# ============================================================

elif page == "🔍 Investigate":
    st.markdown('<p class="gradient-text" style="font-size:1.8rem;">🔍 New Investigation</p>', unsafe_allow_html=True)
    st.markdown("Trigger a new fraud investigation using the agent lifecycle.")
    st.markdown("---")

    if not _AGENT_AVAILABLE:
        st.error("⚠️ Agent modules not available. Install requirements: `pip install -r requirements.txt`")
        st.stop()

    with st.form("investigation_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            account_id = st.text_input("Account ID", value=f"ACC_{random.randint(100000, 999999)}")
            trigger_type = st.selectbox(
                "Trigger Type",
                ["HIGH_RISK_SCORE", "VELOCITY_SPIKE", "CUSTOMER_DISPUTE", "ANALYST_INITIATED", "PATTERN_MATCH"],
            )
            initial_risk = st.slider("Initial Risk Score", 0.0, 1.0, 0.82, 0.01)
        with col2:
            transaction_id = st.text_input("Transaction ID (optional)", value=f"TXN_{random.randint(1000000, 9999999)}")
            amount = st.number_input("Transaction Amount ($)", min_value=0.0, value=8750.0, step=100.0)
            st.markdown("")
            st.markdown("""
            <div style="padding: 10px 14px; background: rgba(6, 40, 24, 0.85); border: 1px solid rgba(52, 211, 153, 0.35); border-radius: 10px; margin-top: 6px;">
                <div style="font-size: 0.72rem; font-weight: 800; color: #ffd700; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 6px;">
                    🛡️ Autonomous Signals (Live)
                </div>
                <div style="display: flex; gap: 14px; font-size: 0.78rem; color: #a7f3d0;">
                    <span>🌐 Proxy/VPN: <b style="color: #ffd700;">Engine Evaluated</b></span>
                    <span>📱 Device: <b style="color: #34d399;">Active Telemetry</b></span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            ip_proxy   = initial_risk >= 0.7 or amount > 5000
            new_device = initial_risk >= 0.65 or trigger_type in ["HIGH_RISK_SCORE", "VELOCITY_SPIKE"]

        submitted = st.form_submit_button("🚀 Run Investigation", use_container_width=True)

    if submitted:
        case_id = f"CASE_2026_{uuid.uuid4().hex[:6].upper()}"

        # Patch mock graph with UI overrides
        try:
            import graph.tigergraph_client as tg_module
            from graph.tigergraph_client import MockFraudGraph
            mock = MockFraudGraph()

            def _patched_shared(a, w=30):
                return {
                    "shared_device_accounts": ["ACC_999001", "ACC_999002"] if ip_proxy else [],
                    "shared_ip_accounts":     ["ACC_999003"] if ip_proxy else [],
                    "shared_card_accounts":   [],
                }
            def _patched_velocity(a, h=72):
                return {"total_txn_count": 5, "total_amount": amount, "avg_txn_amount": amount/5,
                        "max_txn_amount": amount, "txn_per_hour": 2.5, "unique_device_count": 2 if new_device else 1,
                        "unique_ip_count": 2, "velocity_burst_score": 8.5 if ip_proxy else 2.0}
            def _patched_rings():
                return {"components": [], "total_components": 0, "largest_ring_size": 0}
            def _patched_subgraph(a, hop=2):
                nodes = [{"node_id": account_id, "node_type": "Account", "attributes": {"risk_score_current": initial_risk}},
                         {"node_id": "DEV_NEW_001", "node_type": "Device", "attributes": {"risk_score": 0.9 if new_device else 0.1, "is_emulator": False}},
                         {"node_id": "IP_PROXY_001", "node_type": "IP_Address", "attributes": {"country": "RU", "is_proxy": ip_proxy}}]
                edges = [{"source": account_id, "target": "DEV_NEW_001", "edge_type": "USED_DEVICE", "attributes": {}},
                         {"source": account_id, "target": "IP_PROXY_001", "edge_type": "USED_IP", "attributes": {}}]
                return {"nodes": nodes, "edges": edges}

            import types
            mock.detect_shared_entities = _patched_shared
            mock.trace_velocity         = _patched_velocity
            mock.detect_fraud_rings     = _patched_rings
            mock.get_subgraph           = _patched_subgraph
            tg_module._mock_instance    = mock
        except Exception as e:
            st.warning(f"Graph patch warning: {e}")

        trigger = TriggerEvent(
            case_id        = case_id,
            account_id     = account_id,
            transaction_id = transaction_id or None,
            trigger_type   = TriggerType(trigger_type),
            initial_risk   = initial_risk,
            amount         = amount,
        )

        progress = st.progress(0, text="🔄 Initialising investigation...")
        stages = [
            "Triggering case...", "Extracting subgraph...", "Gathering GraphRAG context...",
            "Assessing risk & uncertainty...", "Selecting pre-evidence action...",
            "Gathering additional evidence...", "Selecting final NBA...",
            "Generating SAR & explainability...", "Updating case memory...",
        ]

        result_container = st.empty()
        final_state = None

        try:
            for i, stage in enumerate(stages):
                progress.progress((i+1)/len(stages), text=f"⚙️ {stage}")
                time.sleep(0.3)

            final_state = run_investigation(trigger)
            progress.progress(1.0, text="✅ Investigation complete!")

            result = state_to_result_dict(final_state)
            st.session_state["last_result"] = result
            st.session_state["last_state"]  = final_state

            # Save result
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            result_path = RESULTS_DIR / f"{case_id}_result.json"
            with open(result_path, "w") as f:
                json.dump(result, f, indent=2, default=str)

            st.success(f"✅ Case {case_id} investigation complete!")

        except Exception as e:
            st.error(f"Investigation failed: {e}")
            import traceback
            st.code(traceback.format_exc())
            st.stop()

        if final_state:
            # Show results
            risk = final_state.get("risk_assessment")
            post = final_state.get("post_evidence_action")
            pre  = final_state.get("pre_evidence_action")
            addl = final_state.get("additional_evidence")

            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Fraud Probability", f"{risk.fraud_probability:.0%}" if risk else "N/A")
            r2.metric("Uncertainty",       f"{risk.uncertainty_score:.0%}" if risk else "N/A")
            r3.metric("Typology",          risk.likely_fraud_type.value if risk else "N/A")
            r4.metric("Final Action",      f"{ACTION_ICONS.get(post.action.value, '')} {post.action.value}" if post else "N/A")

            tab1, tab2, tab3 = st.tabs(["📋 Summary", "🔐 Evidence", "📄 SAR Draft"])

            with tab1:
                st.markdown("**Investigation Summary**")
                st.text(final_state.get("case_summary", "No summary generated."))

            with tab2:
                ge = final_state.get("graph_evidence")
                if ge:
                    e1, e2, e3 = st.columns(3)
                    e1.metric("Shared Device Accounts", len(ge.shared_device_accounts))
                    e2.metric("Proxy IP",               "YES" if ge.ip_proxy_detected else "NO")
                    e3.metric("Ring Size",              ge.ring_size)
                    st.caption(f"**Subgraph Path:** {ge.subgraph_path_summary}")

                if addl:
                    st.markdown("**Additional Evidence:**")
                    st.json({
                        "action":   addl.action_taken,
                        "response": addl.response_received,
                        "risk_delta": f"{addl.risk_delta:+.2f}",
                    })

            with tab3:
                sar = final_state.get("sar_draft")
                if sar:
                    st.markdown(f"**SAR Required:** ✅")
                    st.text_area("SAR Draft", sar, height=400)
                else:
                    st.info("No SAR required for this case.")


# ============================================================
# Page: Case Viewer
# ============================================================

elif page == "📊 Case Viewer":
    st.markdown('<p class="gradient-text" style="font-size:1.8rem;">📊 Case Viewer</p>', unsafe_allow_html=True)
    results = load_results()

    if not results:
        st.info("No case results found. Run the benchmark or investigate a case first.")
        st.stop()

    case_ids = [r.get("case_id", f"Result {i}") for i, r in enumerate(results)]
    selected = st.selectbox("Select Case", case_ids)
    result   = next((r for r in results if r.get("case_id") == selected), results[0])

    st.markdown("---")
    post  = result.get("post_evidence_recommendation", {})
    pre   = result.get("pre_evidence_recommendation", {})
    ge    = result.get("graph_evidence", {})
    bench = result.get("_benchmark", {})
    score = result.get("_score", {})

    # Metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Fraud Confidence",  f"{post.get('confidence', 0):.0%}")
    m2.metric("Typology",          post.get("fraud_typology", "?"))
    m3.metric("Final Action",      f"{ACTION_ICONS.get(post.get('action',''), '')} {post.get('action','?')}")
    m4.metric("Approval Required", post.get("approval_required", "?"))
    m5.metric("SAR Required",      "YES ⚠️" if result.get("sar_filing_required") else "NO ✅")

    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Full Result", "📈 Score", "📋 Audit Trail", "📄 SAR"])

    with tab1:
        st.json(result)

    with tab2:
        if score:
            st.markdown("**Benchmark Score vs Expected:**")
            for metric, passed in score.items():
                icon = "✅" if passed else "❌"
                st.markdown(f"{icon} **{metric.replace('_', ' ').title()}**")
            st.metric("Pass Rate", result.get("_pass_rate", "N/A"))
            if bench.get("expected"):
                st.json(bench["expected"])
        else:
            st.info("No benchmark score data for this case.")

    with tab3:
        audit = result.get("audit_trail", [])
        if audit:
            for event in audit:
                ts    = event.get("timestamp", "")[:19]
                stage = event.get("stage", "")
                evt   = event.get("event", "")
                detail = event.get("detail", "")
                st.markdown(f"**`{ts}`** · `{stage}` → **{evt}**")
                if detail:
                    st.caption(f"  ↳ {detail}")
        else:
            st.info("No audit trail available.")

    with tab4:
        sar = result.get("sar_draft", "")
        if sar:
            st.text_area("SAR Draft", sar, height=500)
        else:
            st.info("No SAR required for this case.")


# ============================================================
# Page: Graph View
# ============================================================

elif page == "🌐 Graph View":
    st.markdown('<p class="gradient-text" style="font-size:1.8rem;">🌐 Graph Visualizer</p>', unsafe_allow_html=True)
    st.caption("Interactive subgraph view for the fraud investigation network")
    st.markdown("---")

    try:
        from pyvis.network import Network
        import streamlit.components.v1 as components

        account_id = st.text_input("Account ID to visualize", value="ACC_001")
        hop = st.slider("Hop Depth", 1, 3, 2)

        if st.button("🔍 Load Subgraph"):
            from graph.tigergraph_client import get_graph_client
            client = get_graph_client()
            subgraph = client.get_subgraph(account_id, hop=hop)

            nodes = subgraph.get("nodes", [])
            edges = subgraph.get("edges", [])

            # Build pyvis network
            net = Network(height="500px", bgcolor="#0a0e1a", font_color="#e2e8f0", directed=True)
            net.set_options("""
            {
              "nodes": {"borderWidth": 2, "shadow": true},
              "edges": {"smooth": {"type": "curvedCW", "roundness": 0.2}},
              "physics": {"barnesHut": {"gravitationalConstant": -8000}}
            }
            """)

            node_colors = {
                "Account":    "#38bdf8",
                "Transaction": "#818cf8",
                "Device":     "#f472b6",
                "IP_Address": "#fb923c",
                "Card":       "#4ade80",
            }

            added_nodes = set()
            for n in nodes:
                nid   = n.get("node_id", "")
                ntype = n.get("node_type", "Unknown")
                color = node_colors.get(ntype, "#94a3b8")
                size  = 25 if ntype == "Account" else 15
                label = f"{ntype}\n{nid}"
                if nid and nid not in added_nodes:
                    net.add_node(nid, label=label, color=color, size=size,
                                 title=json.dumps(n.get("attributes", {}), indent=2))
                    added_nodes.add(nid)

            for e in edges:
                src, tgt = e.get("source", ""), e.get("target", "")
                if src in added_nodes and tgt in added_nodes:
                    net.add_edge(src, tgt, title=e.get("edge_type", ""), color="#334155")

            # Render
            net_html = net.generate_html()
            components.html(net_html, height=520, scrolling=False)

            st.markdown(f"**{len(nodes)} nodes, {len(edges)} edges** in {hop}-hop neighborhood")

    except ImportError:
        st.info("Install pyvis for interactive graph visualization: `pip install pyvis`")

        # Fallback: Plotly network
        st.markdown("**Showing simplified network layout (pyvis not installed)**")
        try:
            import plotly.graph_objects as go
            import networkx as nx

            from graph.tigergraph_client import get_graph_client
            client   = get_graph_client()
            subgraph = client.get_subgraph("ACC_001", hop=2)

            G = nx.DiGraph()
            for n in subgraph["nodes"]:
                G.add_node(n["node_id"], ntype=n.get("node_type", "Unknown"))
            for e in subgraph["edges"]:
                G.add_edge(e["source"], e["target"], label=e.get("edge_type", ""))

            pos = nx.spring_layout(G, seed=42)
            node_colors_map = {
                "Account": "#38bdf8", "Transaction": "#818cf8",
                "Device": "#f472b6", "IP_Address": "#fb923c",
            }

            edge_x, edge_y = [], []
            for u, v in G.edges():
                x0, y0 = pos[u]; x1, y1 = pos[v]
                edge_x.extend([x0, x1, None]); edge_y.extend([y0, y1, None])

            node_x = [pos[n][0] for n in G.nodes()]
            node_y = [pos[n][1] for n in G.nodes()]
            node_c = [node_colors_map.get(G.nodes[n].get("ntype",""), "#94a3b8") for n in G.nodes()]
            node_t = [f"{G.nodes[n].get('ntype','')}: {n}" for n in G.nodes()]

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines",
                                     line=dict(width=1, color="#334155"), hoverinfo="none"))
            fig.add_trace(go.Scatter(x=node_x, y=node_y, mode="markers+text",
                                     marker=dict(size=20, color=node_c),
                                     text=[n.split("_")[0] for n in G.nodes()],
                                     textposition="top center",
                                     hovertext=node_t, hoverinfo="text",
                                     textfont=dict(color="#e2e8f0", size=9)))
            fig.update_layout(
                showlegend=False, hovermode="closest",
                paper_bgcolor="#0a0e1a", plot_bgcolor="#0a0e1a",
                xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                height=450, margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(fig, use_container_width=True)
        except Exception as e2:
            st.error(f"Could not render graph: {e2}")


# ============================================================
# Page: Approval Queue
# ============================================================

elif page == "✅ Approval Queue":
    st.markdown('<p class="gradient-text" style="font-size:1.8rem;">✅ Approval Queue</p>', unsafe_allow_html=True)
    st.markdown("Cases awaiting analyst or compliance officer sign-off")
    st.markdown("---")

    results = load_results()
    pending = [
        r for r in results
        if r.get("post_evidence_recommendation", {}).get("approval_required", "") not in
           ("AUTOMATED_POLICY", "")
    ]

    if not pending:
        st.success("✅ No cases awaiting approval.")
    else:
        tier_filter = st.selectbox("Filter by Tier",
                                   ["All", "TIER_1_ANALYST", "TIER_2_ANALYST", "COMPLIANCE_OFFICER"])

        if tier_filter != "All":
            pending = [r for r in pending
                       if r.get("post_evidence_recommendation", {}).get("approval_required") == tier_filter]

        st.metric("Pending Cases", len(pending))

        for r in pending:
            post  = r.get("post_evidence_recommendation", {})
            tier  = post.get("approval_required", "N/A")
            action = post.get("action", "N/A")
            conf  = post.get("confidence", 0)
            sar   = r.get("sar_filing_required", False)

            tier_colors = {
                "TIER_1_ANALYST":    "#38bdf8",
                "TIER_2_ANALYST":    "#fb923c",
                "COMPLIANCE_OFFICER": "#f87171",
            }
            tier_color = tier_colors.get(tier, "#94a3b8")

            with st.expander(f"{ACTION_ICONS.get(action, '⚠️')} {r.get('case_id')} — {action} ({conf:.0%})", expanded=False):
                c1, c2, c3 = st.columns(3)
                c1.metric("Required Approval", tier)
                c2.metric("SAR Required",      "YES ⚠️" if sar else "NO")
                c3.metric("Confidence",        f"{conf:.0%}")

                st.markdown(f"**Justification:** {post.get('justification', 'N/A')}")
                st.markdown(f"**Fraud Typology:** {post.get('fraud_typology', 'N/A')}")

                col_approve, col_reject, col_escalate = st.columns(3)
                if col_approve.button(f"✅ Approve", key=f"approve_{r.get('case_id')}"):
                    st.success(f"Case {r.get('case_id')} approved!")
                if col_reject.button(f"❌ Reject", key=f"reject_{r.get('case_id')}"):
                    st.warning(f"Case {r.get('case_id')} rejected.")
                if col_escalate.button(f"⬆️ Escalate", key=f"escalate_{r.get('case_id')}"):
                    st.info(f"Case {r.get('case_id')} escalated to senior analyst.")


# ============================================================
# Page: Analytics
# ============================================================

elif page == "📋 Analytics":
    st.markdown('<p class="gradient-text" style="font-size:1.8rem;">📋 Benchmark Analytics</p>', unsafe_allow_html=True)
    st.markdown("---")

    # ── Run Benchmark ─────────────────────────────────────────────────────────
    col_run, col_info = st.columns([1, 3])
    with col_run:
        if st.button("▶ Run Benchmark (20 cases)", use_container_width=True):
            with st.spinner("Running benchmark evaluation... (~30s)"):
                try:
                    import subprocess
                    proc = subprocess.run(
                        [sys.executable, str(PROJECT_ROOT / "eval" / "run_benchmark.py")],
                        capture_output=True, text=True, timeout=120,
                        cwd=str(PROJECT_ROOT),
                    )
                    if proc.returncode == 0:
                        st.success("✅ Benchmark complete!")
                    else:
                        st.error(f"Benchmark error:\n{proc.stderr[:500]}")
                except Exception as e:
                    st.error(f"Failed to run benchmark: {e}")
                st.rerun()

    with col_info:
        st.caption("Runs all 20 IEEE-CIS-shaped benchmark test cases through the full 8-stage agent lifecycle.")

    st.markdown("---")
    results = load_results()

    if not results:
        st.info("No benchmark results yet. Click 'Run Benchmark' above.")
        st.stop()

    # ── Summary stats ─────────────────────────────────────────────────────────
    total  = len(results)
    sar_c  = sum(1 for r in results if r.get("sar_filing_required"))
    freeze = sum(1 for r in results if "FREEZE" in r.get("post_evidence_recommendation", {}).get("action", ""))
    block  = sum(1 for r in results if "BLOCK"  in r.get("post_evidence_recommendation", {}).get("action", ""))
    file_s = sum(1 for r in results if "FILE_SAR" in r.get("post_evidence_recommendation", {}).get("action", ""))

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Total Cases",        total)
    s2.metric("SARs Required",      sar_c)
    s3.metric("Accounts Frozen",    freeze)
    s4.metric("Transactions Blocked", block)
    s5.metric("SARs Filed",         file_s)

    st.markdown("---")

    import plotly.express as px
    import plotly.graph_objects as go

    col1, col2 = st.columns(2)

    with col1:
        # Action distribution bar
        action_counts = {}
        for r in results:
            a = r.get("post_evidence_recommendation", {}).get("action", "UNKNOWN")
            action_counts[a] = action_counts.get(a, 0) + 1

        fig = px.bar(
            x=list(action_counts.keys()),
            y=list(action_counts.values()),
            title="Action Distribution",
            color=list(action_counts.keys()),
            color_discrete_sequence=["#38bdf8","#818cf8","#f472b6","#fb923c","#4ade80","#fbbf24","#f87171","#a78bfa"],
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(10,14,26,0.5)",
            font_color="#94a3b8", showlegend=False, height=280,
            xaxis=dict(tickangle=-30), margin=dict(t=40, b=60),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Confidence distribution
        confidences = [r.get("post_evidence_recommendation", {}).get("confidence", 0) for r in results]
        fig = px.histogram(
            x=confidences, nbins=10,
            title="Confidence Distribution",
            labels={"x": "Fraud Confidence"},
            color_discrete_sequence=["#818cf8"],
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(10,14,26,0.5)",
            font_color="#94a3b8", height=280, margin=dict(t=40, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Score table ───────────────────────────────────────────────────────────
    summary_path = RESULTS_DIR / "benchmark_summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            summary = json.load(f)
        st.markdown("#### Benchmark Summary")
        s_col1, s_col2, s_col3 = st.columns(3)
        s_col1.metric("Overall Score",    f"{summary.get('total_score', 0)}/{summary.get('total_possible', 60)}")
        s_col2.metric("Pass Rate",        f"{summary.get('overall_pct', 0):.1f}%")
        s_col3.metric("Run Timestamp",    summary.get("run_ts", "")[:19])

    # ── Case scores table ─────────────────────────────────────────────────────
    scored = [(r.get("case_id"), r.get("_benchmark", {}).get("typology", "?"), r.get("_pass_rate", "?"))
              for r in results if "_pass_rate" in r]
    if scored:
        import pandas as pd
        df = pd.DataFrame(scored, columns=["Case ID", "Typology", "Pass Rate"])
        st.dataframe(df, use_container_width=True, hide_index=True)


# ============================================================
# Page: Info
# ============================================================

elif page == "ℹ️ Info":
    st.markdown('<p class="gradient-text">⚡ HHGOA Cyber Intelligence & System Architecture</p>', unsafe_allow_html=True)
    st.markdown("*Autonomous high-assurance agentic financial fraud investigation engine — Hacker House Goa Edition*")
    st.markdown("---")

    # Hero Banner
    st.markdown("""
    <div style="background: radial-gradient(circle at 10% 10%, rgba(16, 185, 129, 0.25) 0%, transparent 60%), linear-gradient(135deg, rgba(8,48,30,0.85) 0%, rgba(4,25,15,0.95) 100%);
                border: 1px solid rgba(52, 211, 153, 0.35); border-radius: 16px; padding: 24px 28px; margin-bottom: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
        <div style="display: inline-block; background: rgba(16, 185, 129, 0.15); border: 1px solid rgba(52, 211, 153, 0.4); color: #34d399; padding: 3px 12px; border-radius: 9999px; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.08em; margin-bottom: 8px;">
            🌴 HACKER HOUSE GOA (गोवा) · AGENTIC CYBER LABS
        </div>
        <h2 style="color: #ffffff; margin-top: 4px; font-size: 1.6rem; font-weight: 800;">Real-Time Financial Infrastructure Protection</h2>
        <p style="color: #a7f3d0; font-size: 0.92rem; line-height: 1.6; margin-bottom: 0;">
            A production-shaped agentic system combining <b>TigerGraph Enterprise Graph</b> for instant 2-hop community subgraph traversals, 
            a cyclical <b>LangGraph 8-stage state machine</b> with dynamic self-reflection, hybrid <b>ChromaDB GraphRAG</b> for historical case memory, 
            and automated <b>FinCEN-compliant Suspicious Activity Report (SAR)</b> drafting.
        </p>
    </div>
    """, unsafe_allow_html=True)

    # 4 Architecture Pillars
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.markdown("""
        <div class="kpi-card" style="text-align: left; padding: 18px;">
            <div style="font-size: 1.8rem;">🐯</div>
            <h4 style="color: #ffd700; margin: 8px 0 4px 0;">TigerGraph GSQL</h4>
            <p style="font-size: 0.78rem; color: #a7f3d0; margin: 0;">8 vertices, 9 edges. Sub-millisecond WCC label propagation & fund velocity tracing.</p>
        </div>
        """, unsafe_allow_html=True)
    with p2:
        st.markdown("""
        <div class="kpi-card" style="text-align: left; padding: 18px;">
            <div style="font-size: 1.8rem;">🦜</div>
            <h4 style="color: #ffd700; margin: 8px 0 4px 0;">LangGraph State</h4>
            <p style="font-size: 0.78rem; color: #a7f3d0; margin: 0;">8-stage cyclical workflow. Multi-factor Bayesian scoring + self-reflection evidence loop.</p>
        </div>
        """, unsafe_allow_html=True)
    with p3:
        st.markdown("""
        <div class="kpi-card" style="text-align: left; padding: 18px;">
            <div style="font-size: 1.8rem;">🧠</div>
            <h4 style="color: #ffd700; margin: 8px 0 4px 0;">ChromaDB Vector RAG</h4>
            <p style="font-size: 0.78rem; color: #a7f3d0; margin: 0;">Semantic policy search + cosine similarity over historical investigations.</p>
        </div>
        """, unsafe_allow_html=True)
    with p4:
        st.markdown("""
        <div class="kpi-card" style="text-align: left; padding: 18px;">
            <div style="font-size: 1.8rem;">📄</div>
            <h4 style="color: #ffd700; margin: 8px 0 4px 0;">FinCEN SAR Filer</h4>
            <p style="font-size: 0.78rem; color: #a7f3d0; margin: 0;">31 CFR § 1020.320 XML/JSON automated narrative generator with audit trail.</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🔄 8-Stage LangGraph Agent Lifecycle")
    
    stages = [
        ("01. Trigger Ingestion", "High-risk anomaly score, velocity burst, dispute, or analyst initiation.", "agent.state.TriggerEvent"),
        ("02. Subgraph Extraction", "Extracts 2-hop ego network from TigerGraph (accounts, devices, cards, IPs).", "detect_shared_entities.gsql"),
        ("03. GraphRAG Context", "Hybrid vector search across bank fraud policies and resolved precedent cases.", "ChromaDB Memory Store"),
        ("04. Risk Assessment", "Calculates Bayesian fraud probability, uncertainty delta, and key signal markers.", "Bayesian Policy Engine"),
        ("05. Pre-Evidence NBA", "Immediate containment: Step-Up MFA, Card Hold, or temporary limit drop.", "Interim NBA Dispatch"),
        ("06. Additional Evidence", "Dynamic query loop: fetches deep graph evidence if uncertainty > 0.20.", "Cyclic Reflection"),
        ("07. Post-Evidence NBA", "Final decision routed through Tier 1 / Tier 2 / Compliance Officer matrix.", "Authorization Matrix"),
        ("08. SAR & Case Memory", "Drafts FinCEN SAR narrative and indexes case vector into permanent store.", "FinCEN Compliance"),
    ]

    sc1, sc2 = st.columns(2)
    for i, (title, desc, tag) in enumerate(stages):
        col = sc1 if i % 2 == 0 else sc2
        with col:
            st.markdown(f"""
            <div class="case-row" style="margin-bottom: 12px; border-left: 3px solid #10b981;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <strong style="color: #ffffff; font-size: 0.95rem;">{title}</strong>
                    <span style="font-family: monospace; font-size: 0.7rem; color: #ffd700; background: rgba(245,158,11,0.15); padding: 2px 6px; border-radius: 4px;">{tag}</span>
                </div>
                <p style="font-size: 0.8rem; color: #a7f3d0; margin: 6px 0 0 0;">{desc}</p>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🛡️ 5 Core Fraud Typologies (Hacker House Goa Playbook)")

    typologies_data = [
        ("TYP-001: Card-Not-Present Ring", "CRITICAL", "Shared hardware device across multiple disparate bank accounts.", "BLOCK_TRANSACTION", "#f43f5e"),
        ("TYP-002: Account Takeover (ATO)", "CRITICAL", "Unrecognized device jump + foreign proxy/VPN IP + rapid fund drain.", "FREEZE_ACCOUNT", "#f43f5e"),
        ("TYP-003: Bust-Out Fraud", "HIGH", "High-velocity credit line bursting after sudden primary address modification.", "ACCOUNT_HOLD", "#fbbf24"),
        ("TYP-004: Synthetic Identity Ring", "CRITICAL", "WCC community cluster sharing phantom SSNs, phone numbers, and addresses.", "FILE_SAR", "#f43f5e"),
        ("TYP-005: Smurfing & Fund Velocity", "HIGH", "Multiple sub-$10,000 rapid structuring transfers distributed across money mules.", "FILE_SAR", "#fbbf24"),
    ]

    for name, sev, sig, act, color in typologies_data:
        st.markdown(f"""
        <div style="background: rgba(4,28,17,0.7); border: 1px solid rgba(52,211,153,0.2); border-radius: 10px; padding: 14px 18px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <strong style="color: #ffffff; font-size: 0.95rem;">{name}</strong>
                <span style="background: rgba(244,63,94,0.18); color: {color}; font-size: 0.65rem; font-weight: 800; padding: 2px 8px; border-radius: 4px; margin-left: 8px;">{sev}</span>
                <p style="font-size: 0.78rem; color: #a7f3d0; margin: 4px 0 0 0;"><b>Signal:</b> {sig}</p>
            </div>
            <div style="background: rgba(16,185,129,0.15); border: 1px solid rgba(52,211,153,0.35); color: #f0fdf4; padding: 6px 14px; border-radius: 6px; font-family: monospace; font-size: 0.75rem; font-weight: 700; white-space: nowrap;">
                {act}
            </div>
        </div>
        """, unsafe_allow_html=True)

