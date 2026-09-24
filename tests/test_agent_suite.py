"""
tests/test_agent_suite.py (root)
────────────────────────────────
Proxy importing all tests from fraud-investigation-agent/tests/test_agent_suite.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "fraud-investigation-agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from tests.test_agent_suite import (
    test_no_case_id_dependence,
    test_no_data_no_fraud,
    test_policy_rules,
    test_policy_rule_r1,
    test_policy_rule_r2_and_boundaries,
    test_policy_rule_r3,
    test_policy_rule_r4,
    test_policy_rule_r5,
    test_policy_rule_r6,
    test_policy_rule_r7,
    test_policy_rule_r8,
    test_policy_rule_r9,
    test_policy_rule_r10,
    test_answer_schema,
    test_graph_roundtrip,
    test_no_hardcoded_ids,
)
