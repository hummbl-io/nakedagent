import copy
import unittest

from risk_model import assess, compare


def fixture():
    return {
        "schema": "nakedagent-risk-graph/0.1.0", "root": "agent",
        "nodes": ["agent", "file", "provider", "disclosure"],
        "effects": ["disclosure"], "edges": [["agent", "file"]],
        "inventory_complete": False, "required_evidence": ["egress"],
        "evidence": {"egress": {"observed_at": 100, "ttl_seconds": 10, "status": "verified"}},
    }


class RiskTests(unittest.TestCase):
    def test_composed_path_creates_effect(self):
        a = fixture()
        b = copy.deepcopy(a)
        b["edges"] += [["file", "provider"], ["provider", "disclosure"]]
        self.assertEqual(compare(a, b, 105)["added_effects"], ["disclosure"])

    def test_same_effect_different_path_is_reported(self):
        a = fixture()
        a["edges"] += [["file", "disclosure"]]
        b = copy.deepcopy(a)
        b["edges"] += [["file", "provider"], ["provider", "disclosure"]]
        result = compare(a, b, 105)
        self.assertEqual(result["added_effects"], [])
        self.assertEqual(len(result["added_edges"]), 2)

    def test_expiry_exact_boundary(self):
        self.assertTrue(any("stale" in s for s in assess(fixture(), 110)["gaps"]))

    def test_future_and_nan_times(self):
        a = fixture()
        self.assertTrue(any("future" in s for s in assess(a, 99)["gaps"]))
        a["evidence"]["egress"]["observed_at"] = float("nan")
        self.assertTrue(any("invalid" in s for s in assess(a, 105)["gaps"]))

    def test_removing_control_evidence_holds(self):
        a = fixture()
        a["inventory_complete"] = True
        self.assertEqual(assess(a, 105)["gaps"], [])
        a["evidence"] = {}
        self.assertEqual(assess(a, 105)["review_state"], "hold")

    def test_cycle_terminates_and_has_witness(self):
        a = fixture()
        a["edges"] += [["file", "agent"], ["file", "disclosure"]]
        self.assertEqual(assess(a, 105)["witness_paths"]["disclosure"], ["agent", "file", "disclosure"])

    def test_unverified_and_incomplete_never_safe(self):
        a = fixture()
        a["evidence"]["egress"]["status"] = "declared"
        result = assess(a, 105)
        self.assertEqual(len(result["gaps"]), 2)
        self.assertFalse(result["authorizes_execution"])
        self.assertIsNone(result["risk_probability"])

    def test_complete_fresh_graph_still_not_authorization(self):
        a = fixture()
        a["inventory_complete"] = True
        self.assertFalse(assess(a, 105)["authorizes_execution"])

    def test_bad_reference_rejected(self):
        a = fixture()
        a["edges"] += [["agent", "missing"]]
        with self.assertRaises(ValueError):
            assess(a, 105)


if __name__ == "__main__":
    unittest.main()
