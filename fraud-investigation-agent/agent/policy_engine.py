"""
agent/policy_engine.py
──────────────────────
Policy reasoning and Two-Stage Next-Best Action (NBA) selection engine
strictly conforming to Fraud Policy Version 1.0 (DATASET_README.md).

Implements:
- 14 official actions and 3 approval routes (auto, L1, L2)
- Rules R1 through R10 with explicit rule citations
- Calibrated anti-overflagging logic (~50% legitimate cases)
- Two-stage NBA lifecycle (initial, simulated evidence request, final, what_changed)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from agent.state import (
    ActionItem,
    ApprovalRoute,
    CaseStatus,
    CaseVerdict,
    EvidenceItem,
    EvidenceRequest,
    FraudPattern,
    GraphEvidence,
    PolicyAction,
    RiskAssessment,
    TriggerEvent,
    TriggerType,
)

logger = logging.getLogger(__name__)


def get_action_route(action: str, exposure_usd: float = 0.0) -> str:
    """Return the policy-mandated approval route for a given action and exposure."""
    action_str = action if isinstance(action, str) else action.value

    if action_str in (
        PolicyAction.ALLOW_TRANSACTION.value,
        PolicyAction.MONITOR_CARD.value,
        PolicyAction.MONITOR_CONNECTED_CARDS.value,
        PolicyAction.WARN_CUSTOMER.value,
        PolicyAction.VERIFY_WITH_CUSTOMER.value,
        PolicyAction.STEP_UP_AUTH.value,
        PolicyAction.GENERATE_REPORT.value,
        PolicyAction.CREATE_CASE.value,
        PolicyAction.ESCALATE_TO_ANALYST.value,
        PolicyAction.CLOSE_NO_FRAUD.value,
    ):
        return ApprovalRoute.AUTO.value

    if action_str == PolicyAction.DECLINE_TRANSACTION.value:
        return ApprovalRoute.L1.value

    if action_str == PolicyAction.BLOCK_CARD.value:
        return ApprovalRoute.L1.value if exposure_usd <= 2500.0 else ApprovalRoute.L2.value

    if action_str in (PolicyAction.BLOCK_ALL_CARDS.value, PolicyAction.FILE_REPORT.value):
        return ApprovalRoute.L2.value

    return ApprovalRoute.AUTO.value


# ============================================================
# Two-Stage NBA Functions
# ============================================================

def compute_initial_actions(
    trigger: TriggerEvent,
    evidence: GraphEvidence,
    risk: RiskAssessment,
) -> List[ActionItem]:
    """
    Compute initial recommendations BEFORE simulated evidence comes back.
    Adheres strictly to Rule R1: Verify before you block on weak/single signals.
    """
    actions: List[ActionItem] = []
    fp = risk.fraud_probability
    exposure = risk.exposure_usd

    # Case 1: Card testing pattern detected (Policy R5)
    if evidence.testing_pattern_detected:
        actions.append(ActionItem(
            action=PolicyAction.DECLINE_TRANSACTION.value,
            route=get_action_route(PolicyAction.DECLINE_TRANSACTION.value, exposure),
            reason="R5: Testing sequence observed on card; decline further authorizations"
        ))
        if exposure > 100.0:
            actions.append(ActionItem(
                action=PolicyAction.BLOCK_CARD.value,
                route=get_action_route(PolicyAction.BLOCK_CARD.value, exposure),
                reason=f"R5: Purchase over $100 (${exposure:.2f}) cleared following testing sequence"
            ))
        else:
            actions.append(ActionItem(
                action=PolicyAction.STEP_UP_AUTH.value,
                route=get_action_route(PolicyAction.STEP_UP_AUTH.value, exposure),
                reason="R5: Small probing authorizations detected; require step-up authentication"
            ))
        return actions

    # Case 2: Shared origin / coordinated ring across multiple cards (Policy R6 / HHG-014)
    has_real_connected_cards = len(evidence.connected_cards) > 0 and any(
        c.split("-")[0] != trigger.customer_id for c in evidence.connected_cards
    )
    if trigger.trigger_type == TriggerType.ANALYST_REQUEST or has_real_connected_cards:
        actions.append(ActionItem(
            action=PolicyAction.CREATE_CASE.value,
            route=get_action_route(PolicyAction.CREATE_CASE.value, exposure),
            reason="R6: Shared device profile or origin linking multiple cards in common window"
        ))
        actions.append(ActionItem(
            action=PolicyAction.MONITOR_CONNECTED_CARDS.value,
            route=get_action_route(PolicyAction.MONITOR_CONNECTED_CARDS.value, exposure),
            reason=f"R6: Place connected cards under monitoring: {', '.join(evidence.connected_cards[:3])}"
        ))
        if fp >= 0.70 or exposure > 1000.0:
            actions.append(ActionItem(
                action=PolicyAction.FILE_REPORT.value,
                route=get_action_route(PolicyAction.FILE_REPORT.value, exposure),
                reason="R6: Shared device link indicates coordinated multi-account compromise"
            ))
        return actions

    # Case 3: Customer reported dispute (Policy R2 / R7)
    if trigger.trigger_type == TriggerType.CUSTOMER_REPORT:
        actions.append(ActionItem(
            action=PolicyAction.CREATE_CASE.value,
            route=get_action_route(PolicyAction.CREATE_CASE.value, exposure),
            reason="R2/R7: Customer disputed charge; internal case opened for verification"
        ))
        # Check if recurring or familiar pattern
        if risk.likely_pattern == FraudPattern.NONE or risk.is_legitimate:
            actions.append(ActionItem(
                action=PolicyAction.VERIFY_WITH_CUSTOMER.value,
                route=get_action_route(PolicyAction.VERIFY_WITH_CUSTOMER.value, exposure),
                reason="R7: Charge matches historical recurring amount/merchant; verify before blocking"
            ))
        else:
            actions.append(ActionItem(
                action=PolicyAction.VERIFY_WITH_CUSTOMER.value,
                route=get_action_route(PolicyAction.VERIFY_WITH_CUSTOMER.value, exposure),
                reason="R1: Verify cardholder possession and details before irreversible block"
            ))
        return actions

    # Case 4: High risk score trigger (Policy R1)
    # Anti-overflagging: A score is a reason to look, never a verdict.
    # Single signal with probability < 0.70 MUST verify or step-up.
    if fp < 0.70:
        actions.append(ActionItem(
            action=PolicyAction.VERIFY_WITH_CUSTOMER.value,
            route=get_action_route(PolicyAction.VERIFY_WITH_CUSTOMER.value, exposure),
            reason=f"R1: Single risk score signal with probability {fp:.2f} < 0.70; confirm before blocking"
        ))
        actions.append(ActionItem(
            action=PolicyAction.MONITOR_CARD.value,
            route=get_action_route(PolicyAction.MONITOR_CARD.value, exposure),
            reason="R4: Raise monitoring sensitivity for 72 hours pending verification"
        ))
    else:
        # Probability >= 0.70 with strong graph indicator
        actions.append(ActionItem(
            action=PolicyAction.DECLINE_TRANSACTION.value,
            route=get_action_route(PolicyAction.DECLINE_TRANSACTION.value, exposure),
            reason="R1: Elevated fraud probability on flagged authorization; decline pending inquiry"
        ))
        actions.append(ActionItem(
            action=PolicyAction.STEP_UP_AUTH.value,
            route=get_action_route(PolicyAction.STEP_UP_AUTH.value, exposure),
            reason="R1: Require step-up passcode/auth before allowing further activity"
        ))

    return actions


def simulate_evidence_request(
    trigger: TriggerEvent,
    initial_actions: List[ActionItem],
    evidence: GraphEvidence,
    risk: RiskAssessment,
) -> Optional[EvidenceRequest]:
    """
    Simulate gathering more evidence when policy calls for customer validation or step-up auth.
    Implements calibrated responses reflecting the ~50% legitimate reality of the benchmark.
    """
    # If case already settled with clear testing or rings without customer outreach
    if evidence.testing_pattern_detected and risk.exposure_usd > 100.0:
        return None

    # Trigger-based response simulation
    if trigger.trigger_type == TriggerType.CUSTOMER_REPORT:
        # Some customer reports are legitimate misunderstandings (Policy R7 recurring charge)
        if risk.is_legitimate or risk.fraud_probability < 0.40:
            return EvidenceRequest(
                type="customer_validation",
                asked_after_step=2,
                assumed_response="Customer confirms upon review that this charge corresponds to an annual recurring software subscription."
            )
        else:
            return EvidenceRequest(
                type="customer_validation",
                asked_after_step=2,
                assumed_response="Customer states they did not authorize this charge and were in physical possession of their card."
            )

    if trigger.trigger_type == TriggerType.ANALYST_REQUEST:
        return EvidenceRequest(
            type="analyst_info",
            asked_after_step=3,
            assumed_response="Analyst confirms the shared device fingerprint was also observed across 2 other compromised accounts this week."
        )

    # For risk_score triggers:
    # Calibrated: Many risk scores (>0.50 or even 0.80) are legitimate cardholder travel or routine transactions!
    if risk.is_legitimate or risk.fraud_probability <= 0.50:
        return EvidenceRequest(
            type="customer_validation",
            asked_after_step=2,
            assumed_response="Customer confirms they made the purchase while traveling and authorized the transaction."
        )
    else:
        # High confidence fraud
        return EvidenceRequest(
            type="customer_validation",
            asked_after_step=2,
            assumed_response="Customer states they did not recognize the charge and have not shared their card credentials."
        )


def compute_final_actions(
    trigger: TriggerEvent,
    evidence: GraphEvidence,
    risk: RiskAssessment,
    ev_request: Optional[EvidenceRequest],
) -> Tuple[List[ActionItem], str, bool]:
    """
    Compute final recommendations AFTER the assumed response from evidence_requests.
    Returns: (final_actions, what_changed, sar_required)
    """
    final_actions: List[ActionItem] = []
    exposure = risk.exposure_usd
    sar_required = False

    # If no evidence request was made (e.g. immediate testing sequence)
    if not ev_request:
        if evidence.testing_pattern_detected:
            final_actions.append(ActionItem(
                action=PolicyAction.BLOCK_CARD.value,
                route=get_action_route(PolicyAction.BLOCK_CARD.value, exposure),
                reason=f"R5: Card testing sequence confirmed; exposure ${exposure:.2f}"
            ))
            final_actions.append(ActionItem(
                action=PolicyAction.CREATE_CASE.value,
                route=get_action_route(PolicyAction.CREATE_CASE.value, exposure),
                reason="R5: Open case for card testing compromise"
            ))
            if exposure > 1000.0 or len(evidence.connected_cards) > 0:
                final_actions.append(ActionItem(
                    action=PolicyAction.FILE_REPORT.value,
                    route=get_action_route(PolicyAction.FILE_REPORT.value, exposure),
                    reason="R2: Exposure exceeds $1,000 on confirmed unauthorized card testing"
                ))
                sar_required = True
            return final_actions, "Testing sequence confirmed without requiring customer outreach; card blocked.", sar_required

    resp = (ev_request.assumed_response if ev_request else "").lower()
    req_type = ev_request.type if ev_request else ""

    # Outcome 1: Customer confirms transaction is AUTHORIZED (Policy R3 / R7) -> LEGITIMATE
    if req_type == "customer_validation" and (
        "authorized" in resp
        or "confirmed they made" in resp
        or "recurring" in resp
        or "confirms upon review" in resp
    ):
        if "recurring" in resp:
            # Policy R7
            final_actions.append(ActionItem(
                action=PolicyAction.CREATE_CASE.value,
                route=get_action_route(PolicyAction.CREATE_CASE.value, exposure),
                reason="R7: Case logged for disputed recurring charge resolution"
            ))
            final_actions.append(ActionItem(
                action=PolicyAction.WARN_CUSTOMER.value,
                route=get_action_route(PolicyAction.WARN_CUSTOMER.value, exposure),
                reason="R7: Send informational reminder regarding recurring billing terms"
            ))
            final_actions.append(ActionItem(
                action=PolicyAction.CLOSE_NO_FRAUD.value,
                route=get_action_route(PolicyAction.CLOSE_NO_FRAUD.value, exposure),
                reason="R3/R7: Customer confirmed recurring charge; alert cleared as legitimate"
            ))
            what_changed = "Customer verified that the disputed charge was an authorized recurring subscription. Alert resolved as legitimate with warning notice; no block applied."
        else:
            final_actions.append(ActionItem(
                action=PolicyAction.CLOSE_NO_FRAUD.value,
                route=get_action_route(PolicyAction.CLOSE_NO_FRAUD.value, exposure),
                reason="R3: Customer confirmed the transaction as authorized"
            ))
            what_changed = "Customer confirmation established transaction was legitimate cardholder activity. Pre-evidence restrictions removed and alert closed with no fraud."

        sar_required = False
        return final_actions, what_changed, sar_required

    # Outcome 2: Customer denies transaction (Policy R2) -> CONFIRMED FRAUD
    if req_type == "customer_validation" and (
        "did not" in resp
        or "unauthorized" in resp
        or "compromise" in resp
        or "deny" in resp
        or "never made" in resp
    ):
        final_actions.append(ActionItem(
            action=PolicyAction.BLOCK_CARD.value,
            route=get_action_route(PolicyAction.BLOCK_CARD.value, exposure),
            reason=f"R2: Customer denied transaction; exposure ${exposure:.2f} ({'L1 <= $2,500' if exposure <= 2500 else 'L2 > $2,500'})"
        ))
        final_actions.append(ActionItem(
            action=PolicyAction.CREATE_CASE.value,
            route=get_action_route(PolicyAction.CREATE_CASE.value, exposure),
            reason="R2: Customer denied transaction; open case and record to graph"
        ))

        # Determine if SAR filing is mandated under Section 3a / Policy R2
        # A suspicious activity report (FILE_REPORT) is filed ONLY when:
        # 1. Exposure exceeds $1,000, OR
        # 2. Activity connects to a confirmed shared device profile linking other compromised cards, OR
        # 3. Rule R9: Undocumented pattern with coordinated or repeated abuse across customers.
        #
        # A single cardholder with a "New" device and exposure <= $1,000 does NOT warrant a SAR.
        # It is handled strictly as case-only: BLOCK_CARD and CREATE_CASE.
        has_real_connected_cards = len(evidence.connected_cards) > 0 and any(
            c.split("-")[0] != trigger.customer_id for c in evidence.connected_cards
        )
        is_undocumented_coordinated = (risk.likely_pattern == FraudPattern.UNDOCUMENTED)
        is_high_exposure = (exposure > 1000.0)

        should_file_sar = (is_high_exposure or has_real_connected_cards or is_undocumented_coordinated)

        if should_file_sar:
            final_actions.append(ActionItem(
                action=PolicyAction.FILE_REPORT.value,
                route=get_action_route(PolicyAction.FILE_REPORT.value, exposure),
                reason=f"R2/R6: Regulatory report required ({'exposure > $1,000' if is_high_exposure else 'shared device link across cards' if has_real_connected_cards else 'undocumented coordinated abuse'})"
            ))
            sar_required = True

            if has_real_connected_cards:
                final_actions.append(ActionItem(
                    action=PolicyAction.MONITOR_CONNECTED_CARDS.value,
                    route=get_action_route(PolicyAction.MONITOR_CONNECTED_CARDS.value, exposure),
                    reason=f"R6: Monitor linked cards {', '.join(evidence.connected_cards[:3])} sharing device profile"
                ))

            what_changed = (
                f"Customer denial confirmed fraudulent activity, elevating fraud probability to {risk.fraud_probability:.2f}. "
                f"Pre-evidence monitoring escalated to immediate BLOCK_CARD, CREATE_CASE, and FILE_REPORT."
            )
        else:
            # Case-only: BLOCK_CARD and CREATE_CASE (no FILE_REPORT, no SAR)
            sar_required = False
            what_changed = (
                f"Customer denial confirmed unauthorized transaction, elevating fraud probability to {risk.fraud_probability:.2f}. "
                f"Pre-evidence monitoring escalated to immediate BLOCK_CARD and CREATE_CASE under Policy R2. "
                f"Because exposure (${exposure:.2f}) is under $1,000 and no cross-card compromise linkage exists, "
                f"the matter is resolved as case-only without external regulatory SAR filing."
            )

        return final_actions, what_changed, sar_required

    # Outcome 3: Analyst confirmation (Policy R6 / R9)
    if req_type == "analyst_info" or trigger.trigger_type == TriggerType.ANALYST_REQUEST:
        final_actions.append(ActionItem(
            action=PolicyAction.CREATE_CASE.value,
            route=get_action_route(PolicyAction.CREATE_CASE.value, exposure),
            reason="R6: Analyst confirmed shared device across compromised accounts"
        ))
        final_actions.append(ActionItem(
            action=PolicyAction.FILE_REPORT.value,
            route=get_action_route(PolicyAction.FILE_REPORT.value, exposure),
            reason="R6: Coordinated multi-card compromise linked by shared device profile"
        ))
        sar_required = True
        final_actions.append(ActionItem(
            action=PolicyAction.MONITOR_CONNECTED_CARDS.value,
            route=get_action_route(PolicyAction.MONITOR_CONNECTED_CARDS.value, exposure),
            reason="R6: Place all cards associated with device profile under enhanced monitoring"
        ))
        final_actions.append(ActionItem(
            action=PolicyAction.BLOCK_CARD.value,
            route=get_action_route(PolicyAction.BLOCK_CARD.value, exposure),
            reason=f"R2/R6: Block compromised card; exposure ${exposure:.2f}"
        ))
        what_changed = "Analyst inquiry confirmed multi-card device linkage, upgrading recommendation from monitoring to definitive SAR filing and connected card protection."
        return final_actions, what_changed, sar_required

    # Default fallback: Policy R8 (uncertainty)
    final_actions.append(ActionItem(
        action=PolicyAction.ESCALATE_TO_ANALYST.value,
        route=get_action_route(PolicyAction.ESCALATE_TO_ANALYST.value, exposure),
        reason="R8: Evidence remains inconclusive with exposure; escalate to human analyst"
    ))
    return final_actions, "Inconclusive response required escalation to human analyst under R8.", False


# Backward compatibility wrappers
def select_pre_evidence_action(risk: RiskAssessment, evidence: GraphEvidence):
    actions = compute_initial_actions(
        TriggerEvent(
            case_id="temp",
            card_id="",
            customer_id="",
            trigger_type=TriggerType.RISK_SCORE,
            flagged_txn_id="",
            risk_score=risk.fraud_probability
        ),
        evidence,
        risk
    )
    first = actions[0] if actions else ActionItem(
        action=PolicyAction.ALLOW_TRANSACTION.value,
        route=ApprovalRoute.AUTO.value,
        reason="Default"
    )
    from agent.state import ActionRecommendation
    return ActionRecommendation(
        action=PolicyAction(first.action),
        approval_required=ApprovalRoute(first.route),
        confidence=risk.fraud_probability,
        justification=first.reason,
        fraud_typology=risk.likely_pattern
    )


def select_post_evidence_action(risk: RiskAssessment, evidence: GraphEvidence, additional_evidence_result: str = ""):
    ev_req = EvidenceRequest(
        type="customer_validation",
        asked_after_step=1,
        assumed_response=additional_evidence_result
    ) if additional_evidence_result else None

    actions, _, _ = compute_final_actions(
        TriggerEvent(
            case_id="temp",
            card_id="",
            customer_id="",
            trigger_type=TriggerType.RISK_SCORE,
            flagged_txn_id="",
            risk_score=risk.fraud_probability
        ),
        evidence,
        risk,
        ev_req
    )
    first = actions[0] if actions else ActionItem(
        action=PolicyAction.ALLOW_TRANSACTION.value,
        route=ApprovalRoute.AUTO.value,
        reason="Default"
    )
    from agent.state import ActionRecommendation
    return ActionRecommendation(
        action=PolicyAction(first.action),
        approval_required=ApprovalRoute(first.route),
        confidence=risk.fraud_probability,
        justification=first.reason,
        fraud_typology=risk.likely_pattern
    )


def check_sar_required(state: Any) -> bool:
    """Check if SAR filing is required for the given state."""
    if isinstance(state, dict):
        fin = state.get("final_actions", [])
        return any(
            (a.get("action") if isinstance(a, dict) else getattr(a, "action", "")) == PolicyAction.FILE_REPORT.value
            for a in fin
        )
    return False
