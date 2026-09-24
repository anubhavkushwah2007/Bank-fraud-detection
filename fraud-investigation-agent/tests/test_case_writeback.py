"""
tests/test_case_writeback.py
────────────────────────────
Comprehensive test suite verifying:
1. Real Case vertex and edge upsert with read-back verification.
2. Failure handling: written_to_graph=False and graph_case_id="" when write fails.
3. Case retrieval by shared card, device, and region.
4. find_similar_cases returning real CC-#### IDs and agent Case IDs with outcomes.
5. End-to-end workflow case write-back across investigation stages.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.state import TriggerEvent, TriggerType, new_case_state, state_to_result_dict
from agent.workflow import run_investigation
from graph.tigergraph_client import (
    TigerGraphClient,
    UpsertCaseResult,
    get_graph_client,
    set_graph_client,
)


class MockTGConnection:
    """In-memory mock of TigerGraphConnection with vertex, edge, and query support."""

    def __init__(self):
        self.vertices = {
            "Case": {},
            "Card": {},
            "Transaction": {},
            "DeviceProfile": {},
            "BillingRegion": {},
            "ClosedCase": {},
        }
        self.edges = {}  # (s_type, s_id, edge_type, t_type) -> set of t_ids

    def upsertVertex(self, v_type, v_id, attrs):
        self.vertices.setdefault(v_type, {})[str(v_id)] = {
            "v_id": str(v_id),
            "attributes": dict(attrs),
        }
        return 1

    def upsertVertices(self, v_type, vertex_list):
        for v_id, attrs in vertex_list:
            self.upsertVertex(v_type, v_id, attrs)
        return len(vertex_list)

    def upsertEdge(self, s_type, s_id, edge_type, t_type, t_id, attrs=None):
        s_id, t_id = str(s_id), str(t_id)
        self.edges.setdefault((s_type, s_id, edge_type, t_type), set()).add(t_id)
        # Store reverse edge
        rev_edge = f"reverse_{edge_type}"
        self.edges.setdefault((t_type, t_id, rev_edge, s_type), set()).add(s_id)
        return 1

    def upsertEdges(self, s_type, edge_type, t_type, edge_list):
        for item in edge_list:
            s_id, t_id = item[0], item[1]
            self.upsertEdge(s_type, s_id, edge_type, t_type, t_id)
        return len(edge_list)

    def getVerticesById(self, v_type, v_id):
        v = self.vertices.get(v_type, {}).get(str(v_id))
        return [v] if v else []

    def getEdges(self, s_type, s_id, edge_type, t_type):
        targets = self.edges.get((s_type, str(s_id), edge_type, t_type), set())
        return [{"to_id": tid} for tid in targets]

    def getVertices(self, v_type, where="", limit=10):
        return list(self.vertices.get(v_type, {}).values())[:limit]

    def runInstalledQuery(self, query_name, params):
        if query_name == "similar_closed_cases":
            return [
                {
                    "Matches": [
                        {
                            "v_id": "CC-0141",
                            "attributes": {
                                "verdict": "confirmed_fraud",
                                "pattern": params.get("pattern", "card_not_present_fraud"),
                                "total_exposure": 250.0,
                                "analyst_notes": "Past fraud case testing stolen credentials.",
                            },
                        },
                        {
                            "v_id": "CC-0003",
                            "attributes": {
                                "verdict": "cleared",
                                "pattern": params.get("pattern", "card_not_present_fraud"),
                                "total_exposure": 85.0,
                                "analyst_notes": "Legitimate cardholder confirmed transaction.",
                            },
                        },
                    ]
                }
            ]
        elif query_name == "customer_history":
            return [{"Txns": []}]
        elif query_name == "device_neighbors":
            return [{"Cards": [], "Custs": []}]
        return []


class TestCaseWriteBack(unittest.TestCase):

    def setUp(self):
        self.mock_conn = MockTGConnection()
        self.client = TigerGraphClient(conn=self.mock_conn)
        set_graph_client(self.client)

    def tearDown(self):
        set_graph_client(None)


    def test_upsert_case_and_readback(self):
        """Test real write-back and immediate read-back verification."""
        case_data = {
            "case_id": "HHG-001",
            "status": "closed_fraud",
            "verdict": "fraud",
            "fraud_probability": 0.88,
            "pattern": "card_not_present_new_device",
            "exposure_usd": 1250.50,
            "summary": "Confirmed compromise via unauthorized device.",
            "card_id": "C12382-K1",
            "customer_id": "C12382",
            "affected_txn_ids": ["3514030"],
            "similar_prior_cases": ["CC-0141", "HHG-000"],
        }
        res = self.client.upsert_case(case_data)
        self.assertTrue(res.success)
        self.assertEqual(res.vertex_id, "HHG-001")

        # Verify read-back content
        read = self.mock_conn.getVerticesById("Case", "HHG-001")
        self.assertEqual(len(read), 1)
        self.assertEqual(read[0]["attributes"]["verdict"], "fraud")
        self.assertEqual(read[0]["attributes"]["exposure_usd"], 1250.50)

    def test_readback_failure_returns_false(self):
        """Simulate read-back failure: must return success=False and empty vertex_id."""
        self.mock_conn.getVerticesById = MagicMock(return_value=[])
        res = self.client.upsert_case({"case_id": "HHG-FAIL"})
        self.assertFalse(res.success)
        self.assertEqual(res.vertex_id, "")

    def test_case_retrieval_by_shared_card(self):
        """A later investigation must retrieve earlier cases by shared card."""
        self.client.upsert_case({"case_id": "CASE-CARD-A", "card_id": "C09999-K1"})
        cases = self.client.get_cases_by_card("C09999-K1")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["case_id"], "CASE-CARD-A")

    def test_case_retrieval_by_shared_device(self):
        """A later investigation must retrieve earlier cases by shared device profile."""
        dev_id = "SM-G935F | Android 7.0"
        tid = "3400001"
        self.mock_conn.upsertEdge("Transaction", tid, "FROM_DEVICE", "DeviceProfile", dev_id)
        self.client.upsert_case({"case_id": "CASE-DEV-A", "affected_txn_ids": [tid]})
        cases = self.client.get_cases_by_device(dev_id)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["case_id"], "CASE-DEV-A")

    def test_case_retrieval_by_shared_region(self):
        """A later investigation must retrieve earlier cases by shared billing region."""
        region_id = "315"
        tid = "3400002"
        self.mock_conn.upsertEdge("Transaction", tid, "BILLED_IN", "BillingRegion", region_id)
        self.client.upsert_case({"case_id": "CASE-REG-A", "affected_txn_ids": [tid]})
        cases = self.client.get_cases_by_region(region_id)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["case_id"], "CASE-REG-A")

    def test_find_similar_cases_returns_real_ids_and_outcomes(self):
        """find_similar_cases must return real CC-#### IDs and agent Case IDs with outcomes."""
        cases = self.client.find_similar_cases(pattern="card_not_present_fraud")
        self.assertGreater(len(cases), 0)
        self.assertTrue(cases[0]["case_id"].startswith("CC-"))
        self.assertIn("outcome", cases[0])

    def test_workflow_failure_sets_written_to_graph_false(self):
        """If graph write-back fails, final case file must have written_to_graph=False."""
        from config import settings as real_settings
        fail_client = TigerGraphClient(skip_init=True)
        # Patch only OFFLINE_DEV to False while keeping real DATA_DIR so the
        # parquet path lookup doesn't crash with a MagicMock path.
        original_offline = real_settings.OFFLINE_DEV
        try:
            real_settings.OFFLINE_DEV = False
            fail_client.settings = real_settings
            # Leave fail_client.conn as None so upsert_case returns success=False
            set_graph_client(fail_client)
            trigger = TriggerEvent(
                case_id="HHG-FAIL-TEST",
                card_id="C12382-K1",
                customer_id="C12382",
                flagged_txn_id="3514030",
                risk_score=0.88,
                trigger_type=TriggerType.RISK_SCORE,
            )
            final_state = run_investigation(trigger)
            res = state_to_result_dict(final_state)

            self.assertFalse(res["case"]["written_to_graph"])
            self.assertEqual(res["case"]["graph_case_id"], "")
        finally:
            real_settings.OFFLINE_DEV = original_offline

    def test_workflow_success_sets_written_to_graph_true(self):
        """If graph write-back succeeds, final case file has written_to_graph=True and real vertex ID."""
        set_graph_client(self.client)
        trigger = TriggerEvent(
            case_id="HHG-SUCCESS-TEST",
            card_id="C12382-K1",
            customer_id="C12382",
            flagged_txn_id="3514030",
            risk_score=0.88,
            trigger_type=TriggerType.RISK_SCORE,
        )
        final_state = run_investigation(trigger)
        res = state_to_result_dict(final_state)

        self.assertTrue(res["case"]["written_to_graph"])
        self.assertEqual(res["case"]["graph_case_id"], "HHG-SUCCESS-TEST")
        # Verify progression vertices were saved into mock graph
        self.assertIn("HHG-SUCCESS-TEST", self.mock_conn.vertices["Case"])



if __name__ == "__main__":
    unittest.main()
