"""
agent/policy_engine.py
──────────────────────
Pre/Post evidence Next-Best Action (NBA) selection engine.
Applies bank policy rules to select the correct action,
determine the required approval tier, and validate compliance.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from agent.state import (
    ActionRecommendation,
    ApprovalTier,
    FraudTypology,
    GraphEvidence,
    InvestigationAction,
    RiskAssessment,
)


# ─── Load policy document ─────────────────────────────────────────────────────

_POLICIES_PATH = Path(__file__).resolve().parent.parent / "config" / "fraud_policies.json"

def _load_policies() -> Dict[str, Any]:
    try:
        with open(_POLICIES_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

POLICIES = _load_policies()


# ============================================================
# NBA Decision Matrix
# ============================================================

def select_pre_evidence_action(
    risk: RiskAssessment,
    evidence: GraphEvidence,
) -> ActionRecommendation:
    """
    Select the best action to take BEFORE additional evidence is gathered.
    This is primarily an evidence-gathering or low-confidence recommendation.
    """
    fp = risk.fraud_probability
    unc = risk.uncertainty_score

    # ── Rule 1: Very high confidence fraud → immediate block ──────────────────
    if fp >= 0.90 and unc < 0.30:
        return ActionRecommendation(
            action=InvestigationAction.FREEZE_ACCOUNT,
            approval_required=ApprovalTier.TIER_2_ANALYST,
            confidence=fp,
            fraud_typology=risk.likely_fraud_type,
            justification=f"Fraud probability {fp:.0%} with low uncertainty — immediate freeze warranted.",
            policy_refs=["FFIEC Guidance §4.2", "Internal Policy P-FRAUD-02"],
        )

    # ── Rule 2: Proxy/VPN + new device → step-up auth ─────────────────────────
    if evidence.ip_proxy_detected and evidence.new_device_detected:
        return ActionRecommendation(
            action=InvestigationAction.STEP_UP_AUTH,
            approval_required=ApprovalTier.AUTOMATED_POLICY,
            confidence=max(fp, 0.60),
            fraud_typology=risk.likely_fraud_type,
            justification="Proxy IP + new device detected — step-up MFA required before proceeding.",
            policy_refs=["Step-Up Auth Policy SUA-001"],
        )

    # ── Rule 3: High uncertainty → customer outreach ──────────────────────────
    if unc >= 0.40:
        return ActionRecommendation(
            action=InvestigationAction.STEP_UP_AUTH,
            approval_required=ApprovalTier.AUTOMATED_POLICY,
            confidence=fp,
            fraud_typology=risk.likely_fraud_type,
            justification=f"Uncertainty {unc:.0%} is above policy threshold (40%) — customer validation required.",
            policy_refs=["Evidence Policy EP-003"],
        )

    # ── Rule 4: Moderate risk → watchlist ────────────────────────────────────
    if 0.50 <= fp < 0.75:
        return ActionRecommendation(
            action=InvestigationAction.ADD_TO_WATCHLIST,
            approval_required=ApprovalTier.AUTOMATED_POLICY,
            confidence=fp,
            fraud_typology=risk.likely_fraud_type,
            justification=f"Risk {fp:.0%} warrants enhanced monitoring before evidence gathering.",
            policy_refs=["Monitoring Policy MON-002"],
        )

    # ── Rule 5: Low risk → allow ──────────────────────────────────────────────
    return ActionRecommendation(
        action=InvestigationAction.ALLOW_TRANSACTION,
        approval_required=ApprovalTier.AUTOMATED_POLICY,
        confidence=1.0 - fp,
        fraud_typology=FraudTypology.UNKNOWN,
        justification=f"Risk {fp:.0%} below alert threshold — transaction may proceed.",
        policy_refs=["Risk Policy RP-001"],
    )


def select_post_evidence_action(
    risk: RiskAssessment,
    evidence: GraphEvidence,
    additional_evidence_result: str = "",
) -> ActionRecommendation:
    """
    Select the definitive NBA after all evidence has been gathered.
    Maps the synthesised risk + evidence to a final action with correct approval tier.
    """
    fp  = risk.fraud_probability
    typ = risk.likely_fraud_type
    ae  = additional_evidence_result  # e.g. "TRANSACTION_UNRECOGNIZED", "REPORTED_FRAUD"

    # ── Evidence signals ──────────────────────────────────────────────────────
    confirmed_fraud = ae in ("TRANSACTION_UNRECOGNIZED", "REPORTED_FRAUD", "AUTH_FAILED", "BLOCKED")
    customer_cleared = ae in ("TRANSACTION_RECOGNIZED", "AUTH_OK")

    # ── If customer confirmed legitimate → allow or watchlist ─────────────────
    if customer_cleared and fp < 0.75:
        return ActionRecommendation(
            action=InvestigationAction.ALLOW_TRANSACTION,
            approval_required=ApprovalTier.AUTOMATED_POLICY,
            confidence=0.90,
            fraud_typology=FraudTypology.UNKNOWN,
            justification="Customer confirmed the transaction as legitimate via step-up auth or outreach.",
            policy_refs=["Customer Validation Policy CVP-001"],
        )

    # ── SAR-mandatory typologies ───────────────────────────────────────────────
    sar_typologies = {
        FraudTypology.SYNTHETIC_IDENTITY,
        FraudTypology.SMURFING_VELOCITY,
    }
    if (fp >= 0.85 or confirmed_fraud) and typ in sar_typologies:
        return ActionRecommendation(
            action=InvestigationAction.FILE_SAR,
            approval_required=ApprovalTier.COMPLIANCE_OFFICER,
            confidence=min(fp + 0.05, 1.0),
            fraud_typology=typ,
            justification=(
                f"SAR mandatory for {typ.value} typology with {fp:.0%} fraud probability. "
                f"Customer response: '{ae}'."
            ),
            policy_refs=["31 U.S.C. § 5318(g)", "FinCEN SAR Policy"],
        )

    # ── Account Takeover / CNP Ring → freeze account ─────────────────────────
    if (fp >= 0.75 or confirmed_fraud) and typ in (
        FraudTypology.ACCOUNT_TAKEOVER,
        FraudTypology.CARD_NOT_PRESENT_RING,
    ):
        action = (
            InvestigationAction.FREEZE_ACCOUNT
            if typ == FraudTypology.ACCOUNT_TAKEOVER
            else InvestigationAction.BLOCK_TRANSACTION
        )
        sar = fp >= 0.85
        return ActionRecommendation(
            action=action,
            approval_required=ApprovalTier.TIER_2_ANALYST,
            confidence=fp,
            fraud_typology=typ,
            justification=(
                f"{typ.value} detected with {fp:.0%} fraud probability. "
                f"Evidence: {ae}. Shared devices: {len(evidence.shared_device_accounts)}."
            ),
            policy_refs=["ATO Policy ATO-007", "FFIEC §5.1"],
        )

    # ── Bust-out → account hold ───────────────────────────────────────────────
    if (fp >= 0.75 or confirmed_fraud) and typ == FraudTypology.BUST_OUT:
        return ActionRecommendation(
            action=InvestigationAction.ACCOUNT_HOLD,
            approval_required=ApprovalTier.TIER_2_ANALYST,
            confidence=fp,
            fraud_typology=typ,
            justification=f"Bust-out pattern detected. Account hold to preserve assets during investigation.",
            policy_refs=["Bust-Out Policy BO-003"],
        )

    # ── Ring detected → escalate + watchlist ─────────────────────────────────
    if evidence.ring_size >= 3:
        return ActionRecommendation(
            action=InvestigationAction.ESCALATE_TO_ANALYST,
            approval_required=ApprovalTier.TIER_2_ANALYST,
            confidence=fp,
            fraud_typology=typ,
            justification=f"Fraud ring of {evidence.ring_size} accounts detected. Manual investigation required.",
            policy_refs=["Ring Detection Policy RD-002"],
        )

    # ── High risk without clear typology → escalate ───────────────────────────
    if fp >= 0.75:
        return ActionRecommendation(
            action=InvestigationAction.ESCALATE_TO_ANALYST,
            approval_required=ApprovalTier.TIER_1_ANALYST,
            confidence=fp,
            fraud_typology=typ,
            justification=f"High fraud probability {fp:.0%} without definitive typology. Analyst review required.",
            policy_refs=["Escalation Policy ESC-001"],
        )

    # ── Moderate risk → watchlist ─────────────────────────────────────────────
    if fp >= 0.50:
        return ActionRecommendation(
            action=InvestigationAction.ADD_TO_WATCHLIST,
            approval_required=ApprovalTier.AUTOMATED_POLICY,
            confidence=fp,
            fraud_typology=typ,
            justification=f"Moderate risk {fp:.0%} — enhanced monitoring sufficient.",
            policy_refs=["Monitoring Policy MON-002"],
        )

    # ── Low risk → allow ──────────────────────────────────────────────────────
    return ActionRecommendation(
        action=InvestigationAction.ALLOW_TRANSACTION,
        approval_required=ApprovalTier.AUTOMATED_POLICY,
        confidence=1.0 - fp,
        fraud_typology=FraudTypology.UNKNOWN,
        justification=f"Post-evidence risk {fp:.0%} — transaction is within acceptable risk tolerance.",
        policy_refs=["Risk Policy RP-001"],
    )


def check_sar_required(
    risk: RiskAssessment,
    action: ActionRecommendation,
    total_amount: float = 0.0,
) -> Tuple[bool, str]:
    """
    Determine if a SAR filing is mandatory given policy rules.

    Returns:
        (sar_required: bool, reason: str)
    """
    thresholds = POLICIES.get("risk_thresholds", {})
    sar_threshold = thresholds.get("sar_mandatory", 0.85)
    suspicious_amount = POLICIES.get("sar_filing_rules", {}).get("suspicious_amount_threshold", 5000)

    sar_typologies = {"SYNTHETIC_IDENTITY", "SMURFING_VELOCITY"}

    reasons: List[str] = []

    if risk.fraud_probability >= sar_threshold:
        reasons.append(f"Fraud probability {risk.fraud_probability:.0%} ≥ SAR threshold {sar_threshold:.0%}.")

    if risk.likely_fraud_type.value in sar_typologies:
        reasons.append(f"Typology '{risk.likely_fraud_type.value}' mandates SAR filing.")

    if total_amount >= suspicious_amount and risk.fraud_probability >= 0.70:
        reasons.append(f"Amount ${total_amount:,.2f} ≥ suspicious threshold ${suspicious_amount:,}.")

    if action.action == InvestigationAction.FILE_SAR:
        reasons.append("Post-evidence NBA recommends SAR filing.")

    if reasons:
        return True, " ".join(reasons)
    return False, ""


def validate_action_compliance(action: ActionRecommendation, policies: Dict[str, Any]) -> List[str]:
    """
    Validate that a recommended action complies with policy rules.
    Returns a list of any compliance violations.
    """
    violations: List[str] = []
    matrix = policies.get("action_authorization_matrix", {})
    action_policy = matrix.get(action.action.value, {})

    max_fp = action_policy.get("max_fraud_probability", 1.0)
    required_tier = action_policy.get("approval_tier", "AUTOMATED_POLICY")

    if action.confidence > max_fp:
        violations.append(
            f"Action {action.action.value} has confidence {action.confidence:.2f} "
            f"exceeding policy max {max_fp:.2f}."
        )

    # Verify approval tier is at least as strict as policy requires
    tier_ranks = {
        "AUTOMATED_POLICY": 0,
        "TIER_1_ANALYST": 1,
        "TIER_2_ANALYST": 2,
        "COMPLIANCE_OFFICER": 3,
    }
    rec_rank  = tier_ranks.get(action.approval_required.value, 0)
    pol_rank  = tier_ranks.get(required_tier, 0)
    if rec_rank < pol_rank:
        violations.append(
            f"Action {action.action.value} requires {required_tier} approval, "
            f"but only {action.approval_required.value} specified."
        )

    return violations
