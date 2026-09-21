"""
agent/tools.py
──────────────
Mock external action tools simulating real financial system integrations.
Each tool returns realistic mock responses and logs the action taken.

Tools available to the agent:
  1. trigger_step_up_mfa      – MFA/OTP challenge
  2. send_customer_sms        – Transaction validation SMS
  3. send_customer_email      – Transaction validation email
  4. freeze_card              – Card freeze action
  5. place_account_hold       – Legal hold on account funds
  6. freeze_account           – Full account freeze
  7. add_to_watchlist         – Enhanced monitoring flag
  8. file_sar_report          – SAR filing stub
"""
from __future__ import annotations

import random
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from langchain_core.tools import tool


# ─── Seeded RNG for reproducible demo results ──────────────────────────────────
_rng = random.Random(42)


def _mock_delay(min_ms: int = 100, max_ms: int = 500) -> None:
    """Simulate network latency."""
    time.sleep(_rng.randint(min_ms, max_ms) / 1000.0)


def _timestamp() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ─── Tool 1: Step-Up MFA ──────────────────────────────────────────────────────

@tool
def trigger_step_up_mfa(account_id: str, transaction_id: str, method: str = "OTP_SMS") -> Dict[str, Any]:
    """
    Trigger a step-up MFA challenge for the customer.
    Simulates sending an OTP and receiving a response.

    Args:
        account_id:     Target account identifier.
        transaction_id: Transaction requiring verification.
        method:         Auth method — OTP_SMS | OTP_EMAIL | TOTP_APP | BIOMETRIC.

    Returns:
        dict with response_status, mfa_reference_id, and latency_ms.
    """
    _mock_delay(200, 800)

    # Simulate realistic MFA outcomes
    outcomes = [
        ("VERIFIED",   0.55),   # Customer completes MFA
        ("TIMEOUT",    0.20),   # Customer doesn't respond
        ("FAILED",     0.15),   # Wrong OTP
        ("BLOCKED",    0.10),   # Account locked after retries
    ]
    statuses, weights = zip(*outcomes)
    status = _rng.choices(list(statuses), weights=list(weights), k=1)[0]

    ref_id = f"MFA-{uuid.uuid4().hex[:8].upper()}"

    return {
        "tool":           "trigger_step_up_mfa",
        "account_id":     account_id,
        "transaction_id": transaction_id,
        "method":         method,
        "mfa_reference_id": ref_id,
        "response_status": status,
        "response_ts":    _timestamp(),
        "latency_ms":     _rng.randint(200, 800),
        "risk_signal":    "AUTH_FAILED" if status in ("FAILED", "BLOCKED") else
                          "AUTH_TIMEOUT" if status == "TIMEOUT" else "AUTH_OK",
        "interpretation": {
            "VERIFIED": "Customer confirmed transaction — reduces fraud probability.",
            "TIMEOUT":  "No response received — uncertainty remains high.",
            "FAILED":   "Wrong OTP submitted — raises fraud probability.",
            "BLOCKED":  "Account locked after repeated failures — strong fraud signal.",
        }.get(status, ""),
    }


# ─── Tool 2: Customer SMS Outreach ────────────────────────────────────────────

@tool
def send_customer_sms(account_id: str, transaction_id: str, amount: float) -> Dict[str, Any]:
    """
    Send an SMS to the customer asking them to validate a suspicious transaction.

    Args:
        account_id:     Account owner's ID.
        transaction_id: Transaction to be validated.
        amount:         Transaction amount in USD.

    Returns:
        dict with response_received and interpretation.
    """
    _mock_delay(300, 1200)

    responses = [
        ("TRANSACTION_RECOGNIZED",   0.40),
        ("TRANSACTION_UNRECOGNIZED", 0.35),
        ("NO_RESPONSE",              0.15),
        ("REPORTED_FRAUD",           0.10),
    ]
    resp_opts, weights = zip(*responses)
    response = _rng.choices(list(resp_opts), weights=list(weights), k=1)[0]

    sms_id = f"SMS-{uuid.uuid4().hex[:8].upper()}"

    return {
        "tool":             "send_customer_sms",
        "account_id":       account_id,
        "transaction_id":   transaction_id,
        "amount":           amount,
        "sms_reference_id": sms_id,
        "response_received": response,
        "response_status":  "SUCCESS" if response != "NO_RESPONSE" else "TIMEOUT",
        "response_ts":      _timestamp(),
        "interpretation": {
            "TRANSACTION_RECOGNIZED":   "Customer confirms the transaction — likely legitimate.",
            "TRANSACTION_UNRECOGNIZED": "Customer does not recognize the transaction — strong fraud signal.",
            "NO_RESPONSE":              "Customer did not respond — uncertainty remains.",
            "REPORTED_FRAUD":           "Customer explicitly reported fraud — confirmed ATO or CNP.",
        }.get(response, ""),
    }


# ─── Tool 3: Customer Email Outreach ──────────────────────────────────────────

@tool
def send_customer_email(account_id: str, transaction_id: str, amount: float) -> Dict[str, Any]:
    """
    Send an email to the customer for transaction validation (alternative to SMS).

    Args:
        account_id:     Account owner's ID.
        transaction_id: Transaction to be validated.
        amount:         Transaction amount in USD.

    Returns:
        dict with response_received and interpretation.
    """
    _mock_delay(500, 2000)

    responses = [
        ("TRANSACTION_RECOGNIZED",   0.35),
        ("TRANSACTION_UNRECOGNIZED", 0.30),
        ("NO_RESPONSE",              0.25),
        ("REPORTED_FRAUD",           0.10),
    ]
    resp_opts, weights = zip(*responses)
    response = _rng.choices(list(resp_opts), weights=list(weights), k=1)[0]

    email_id = f"EMAIL-{uuid.uuid4().hex[:8].upper()}"

    return {
        "tool":              "send_customer_email",
        "account_id":        account_id,
        "transaction_id":    transaction_id,
        "amount":            amount,
        "email_reference_id": email_id,
        "response_received": response,
        "response_status":   "SUCCESS" if response != "NO_RESPONSE" else "TIMEOUT",
        "response_ts":       _timestamp(),
        "interpretation": {
            "TRANSACTION_RECOGNIZED":   "Customer confirms via email — reduces fraud probability.",
            "TRANSACTION_UNRECOGNIZED": "Customer disputes via email — escalation warranted.",
            "NO_RESPONSE":              "No email response — insufficient confirmation.",
            "REPORTED_FRAUD":           "Fraud confirmed by customer — immediate freeze recommended.",
        }.get(response, ""),
    }


# ─── Tool 4: Freeze Card ──────────────────────────────────────────────────────

@tool
def freeze_card(card_id: str, account_id: str, reason: str = "FRAUD_SUSPICION") -> Dict[str, Any]:
    """
    Freeze a specific card to prevent further transactions.
    Reversible by Tier-1 analyst.

    Args:
        card_id:    Card to freeze.
        account_id: Owning account.
        reason:     Freeze reason code.

    Returns:
        dict with freeze_reference_id and effective_ts.
    """
    _mock_delay(100, 300)

    freeze_id = f"FRZ-{uuid.uuid4().hex[:8].upper()}"

    return {
        "tool":             "freeze_card",
        "card_id":          card_id,
        "account_id":       account_id,
        "reason":           reason,
        "freeze_reference_id": freeze_id,
        "status":           "CARD_FROZEN",
        "effective_ts":     _timestamp(),
        "reversible":       True,
        "reversal_requires": "TIER_1_ANALYST",
        "message":          f"Card {card_id} successfully frozen. Reference: {freeze_id}",
    }


# ─── Tool 5: Place Account Hold ───────────────────────────────────────────────

@tool
def place_account_hold(account_id: str, hold_amount: float, reason: str = "INVESTIGATION_HOLD") -> Dict[str, Any]:
    """
    Place a legal hold on a specified amount in an account.
    Requires Tier-2 Analyst approval. Irreversible without compliance sign-off.

    Args:
        account_id:  Account to hold.
        hold_amount: Amount to freeze (USD). 0.0 = full balance.
        reason:      Hold reason code.

    Returns:
        dict with hold_reference_id and compliance details.
    """
    _mock_delay(150, 400)

    hold_id = f"HOLD-{uuid.uuid4().hex[:8].upper()}"

    return {
        "tool":           "place_account_hold",
        "account_id":     account_id,
        "hold_amount":    hold_amount if hold_amount > 0 else "FULL_BALANCE",
        "reason":         reason,
        "hold_reference_id": hold_id,
        "status":         "HOLD_PLACED",
        "effective_ts":   _timestamp(),
        "reversible":     False,
        "reversal_requires": "COMPLIANCE_OFFICER",
        "regulatory_ref": "12 CFR Part 229 (Reg CC)",
        "message":        f"Legal hold placed on account {account_id}. Reference: {hold_id}",
    }


# ─── Tool 6: Freeze Account ───────────────────────────────────────────────────

@tool
def freeze_account(account_id: str, reason: str = "FRAUD_INVESTIGATION") -> Dict[str, Any]:
    """
    Freeze all account activity (debit/credit blocked) pending investigation.
    Requires Tier-2 Analyst approval.

    Args:
        account_id: Account to freeze.
        reason:     Freeze reason code.

    Returns:
        dict with freeze_reference_id and affected restrictions.
    """
    _mock_delay(200, 500)

    freeze_id = f"ACCT-FRZ-{uuid.uuid4().hex[:8].upper()}"

    return {
        "tool":             "freeze_account",
        "account_id":       account_id,
        "reason":           reason,
        "freeze_reference_id": freeze_id,
        "status":           "ACCOUNT_FROZEN",
        "restrictions":     ["DEBIT_BLOCKED", "CREDIT_BLOCKED", "ACH_BLOCKED", "WIRE_BLOCKED"],
        "effective_ts":     _timestamp(),
        "reversible":       True,
        "reversal_requires": "TIER_2_ANALYST",
        "customer_notification": "REQUIRED_WITHIN_5_DAYS",
        "message":          f"Account {account_id} fully frozen. Reference: {freeze_id}",
    }


# ─── Tool 7: Add to Watchlist ─────────────────────────────────────────────────

@tool
def add_to_watchlist(account_id: str, risk_level: str = "HIGH", reason: str = "") -> Dict[str, Any]:
    """
    Flag an account for enhanced monitoring without blocking transactions.
    Automated — no analyst approval required.

    Args:
        account_id: Account to watch.
        risk_level: MEDIUM | HIGH | CRITICAL.
        reason:     Reason for watchlist placement.

    Returns:
        dict with watchlist_reference_id and monitoring parameters.
    """
    _mock_delay(50, 200)

    wl_id = f"WL-{uuid.uuid4().hex[:8].upper()}"

    monitoring_params = {
        "MEDIUM":   {"txn_review_pct": 25, "review_threshold": 5000,  "alert_velocity": 5},
        "HIGH":     {"txn_review_pct": 75, "review_threshold": 1000,  "alert_velocity": 3},
        "CRITICAL": {"txn_review_pct": 100, "review_threshold": 0,    "alert_velocity": 1},
    }.get(risk_level, {"txn_review_pct": 50, "review_threshold": 2000, "alert_velocity": 5})

    return {
        "tool":               "add_to_watchlist",
        "account_id":         account_id,
        "risk_level":         risk_level,
        "reason":             reason,
        "watchlist_reference_id": wl_id,
        "status":             "WATCHLIST_ADDED",
        "monitoring_params":  monitoring_params,
        "effective_ts":       _timestamp(),
        "review_frequency":   "DAILY",
        "expiry_days":        90,
        "message":            f"Account {account_id} added to {risk_level} watchlist. Reference: {wl_id}",
    }


# ─── Tool 8: File SAR Report ──────────────────────────────────────────────────

@tool
def file_sar_report(
    account_id: str,
    case_id: str,
    fraud_typology: str,
    narrative: str,
    amount_involved: float,
) -> Dict[str, Any]:
    """
    File a Suspicious Activity Report (SAR) stub with FinCEN.
    Requires Compliance Officer approval before actual submission.

    Args:
        account_id:      Subject account.
        case_id:         Internal case reference.
        fraud_typology:  Detected typology (e.g. ACCOUNT_TAKEOVER).
        narrative:       SAR narrative text.
        amount_involved: Total suspicious amount (USD).

    Returns:
        dict with sar_reference_id, BSA ID stub, and filing deadline.
    """
    _mock_delay(300, 600)

    sar_id  = f"SAR-{uuid.uuid4().hex[:10].upper()}"
    bsa_id  = f"BSA-{uuid.uuid4().hex[:12].upper()}"

    return {
        "tool":              "file_sar_report",
        "account_id":        account_id,
        "case_id":           case_id,
        "sar_reference_id":  sar_id,
        "bsa_id_stub":       bsa_id,
        "fraud_typology":    fraud_typology,
        "amount_involved":   amount_involved,
        "narrative_preview": narrative[:200] + "..." if len(narrative) > 200 else narrative,
        "status":            "PENDING_COMPLIANCE_REVIEW",
        "filing_deadline":   "30 days from detection",
        "regulatory_ref":    "31 U.S.C. § 5318(g) | FinCEN SAR Form 111",
        "effective_ts":      _timestamp(),
        "message":           f"SAR draft created for case {case_id}. Awaiting compliance sign-off. Ref: {sar_id}",
    }


# ─── Tool registry (for LangGraph binding) ────────────────────────────────────

ALL_TOOLS = [
    trigger_step_up_mfa,
    send_customer_sms,
    send_customer_email,
    freeze_card,
    place_account_hold,
    freeze_account,
    add_to_watchlist,
    file_sar_report,
]

TOOL_MAP = {t.name: t for t in ALL_TOOLS}
