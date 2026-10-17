import copy
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from admission_pilot import LabBroker, Observation
from contract import VERSION, canonical, digest, loads, validate


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.artifact = root / "artifact.txt"
        self.artifact.write_bytes(b"reviewed fixture component")
        self.fixture = root / "public.txt"
        self.fixture.write_bytes(b"public fixture")
        self.contract = {
            "schema": VERSION, "run_id": "lab-run", "principal": "lab-worker",
            "policy_sha256": "a" * 64, "configuration_sha256": "b" * 64,
            "dependency_graph_sha256": "c" * 64,
            "components": [{"id": "fixture-component", "sha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest(), "dependencies": []}],
            "grants": [{"operation": "read_fixture", "resource": "lab:public-fixture"}],
            "required_evidence": ["fixture-enrolled"], "max_actions": 1, "expires_at": 200,
        }
        self.broker = LabBroker(
            self.contract, owner_grant_sha256=digest(self.contract), fixture=self.fixture,
            fixture_sha256=hashlib.sha256(self.fixture.read_bytes()).hexdigest(),
            artifacts={"fixture-component": self.artifact}, configuration_sha256="b" * 64,
            graph_sha256="c" * 64,
            observations={"fixture-enrolled": Observation(90, 150, "b" * 64, "verified")},
            kernel=lambda _: {"decision": "allow", "required_controls": [], "enforcement_status": "test_stub"},
            clock=lambda: 100,
        )
        self.action = {"action_id": "a1", "run_id": "lab-run", "principal": "lab-worker",
                       "contract_sha256": digest(self.contract), "operation": "read_fixture",
                       "resource": "lab:public-fixture"}

    def assert_no_effect(self, result):
        self.assertNotEqual(result["decision"], "completed")
        self.assertEqual(self.broker.used, 0)
        self.assertFalse(any(e["decision"] == "reserved" for e in self.broker.events))

    def test_valid_contract_roundtrip(self):
        self.assertEqual(loads(canonical(self.contract)), self.contract)

    def test_schema_rejects_unknown_missing_boolean_and_duplicate(self):
        for edit in (lambda c: c.update(extra=True), lambda c: c.pop("run_id"),
                     lambda c: c.update(max_actions=True),
                     lambda c: c["required_evidence"].append("fixture-enrolled")):
            c = copy.deepcopy(self.contract)
            edit(c)
            with self.assertRaises(ValueError):
                validate(c)

    def test_duplicate_json_keys_and_oversized_input(self):
        for raw in (b'{"schema":1,"schema":2}', b' ' * 65537, b'{"x":NaN}'):
            with self.assertRaises(ValueError):
                loads(raw)

    def test_dependency_references_and_component_identity(self):
        c = copy.deepcopy(self.contract)
        c["components"][0]["dependencies"] = ["absent"]
        with self.assertRaises(ValueError):
            validate(c)
        c = copy.deepcopy(self.contract)
        second = copy.deepcopy(c["components"][0])
        second["sha256"] = "d" * 64
        c["components"].append(second)
        with self.assertRaises(ValueError):
            validate(c)

    def test_allowed_effect_is_reserved_and_completed(self):
        result = self.broker.dispatch(self.action)
        self.assertEqual(result["decision"], "completed")
        self.assertEqual([e["decision"] for e in self.broker.events], ["reserved", "completed"])

    def test_claimed_evidence_in_action_rejected(self):
        self.action["verified"] = "true"
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_untrusted_target_path_rejected(self):
        self.action["resource"] = "C:/Users/Owner/.ssh/id_ed25519"
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_owner_binding_and_principal_cannot_be_forged(self):
        self.broker.owner_grant_sha256 = "e" * 64
        self.assert_no_effect(self.broker.dispatch(self.action))
        self.action["principal"] = "owner"
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_stale_missing_unverified_and_unbound_evidence(self):
        cases = [None, Observation(90, 100, "b" * 64, "verified"),
                 Observation(101, 150, "b" * 64, "verified"),
                 Observation(90, 150, "d" * 64, "verified"),
                 Observation(90, 150, "b" * 64, "declared")]
        for observation in cases:
            self.broker.observations["fixture-enrolled"] = observation
            self.assert_no_effect(self.broker.dispatch(self.action))

    def test_all_nonallow_kernel_routes_block_dispatch(self):
        for decision in ("ask", "deny", "constrain", "escalate", "require_more_evidence", "bogus"):
            self.broker.kernel = lambda _, d=decision: {"decision": d, "required_controls": []}
            self.assert_no_effect(self.broker.dispatch(self.action))

    def test_unsupported_kernel_controls_block_dispatch(self):
        self.broker.kernel = lambda _: {"decision": "allow", "required_controls": ["unknown-control"]}
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_kernel_failure_holds(self):
        def fail(_):
            raise RuntimeError("kernel offline")
        self.broker.kernel = fail
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_artifact_drift_before_dispatch(self):
        self.artifact.write_bytes(b"changed")
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_config_drift_during_kernel_call(self):
        def drift(_):
            self.broker.configuration_sha256 = "e" * 64
            return {"decision": "allow", "required_controls": []}
        self.broker.kernel = drift
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_new_appendage_invalidates_binding(self):
        self.broker.artifacts["new-plugin"] = self.artifact
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_caller_mutation_does_not_change_admitted_action_record(self):
        def mutate(_):
            self.action["action_id"] = "changed-by-caller"
            return {"decision": "allow", "required_controls": []}
        self.broker.kernel = mutate
        result = self.broker.dispatch(self.action)
        self.assertEqual(result["action_id"], "a1")

    def test_revocation_and_expiry(self):
        self.broker.revoked = True
        self.assert_no_effect(self.broker.dispatch(self.action))
        self.broker.revoked = False
        self.broker.clock = lambda: 200
        self.assert_no_effect(self.broker.dispatch(self.action))

    def test_concurrent_budget_cannot_overspend(self):
        actions = [{**self.action, "action_id": str(i)} for i in range(12)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(self.broker.dispatch, actions))
        self.assertEqual(sum(r["decision"] == "completed" for r in results), 1)
        self.assertEqual(self.broker.used, 1)

    def test_replay_denied(self):
        self.broker.dispatch(self.action)
        self.assertIn("replayed_action", self.broker.dispatch(self.action)["reasons"])

    def test_changed_fixture_not_reported_as_success(self):
        self.fixture.write_bytes(b"changed")
        result = self.broker.dispatch(self.action)
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(self.broker.used, 1)  # attempt consumes reservation

    def test_exported_schema_matches_module(self):
        from contract import SCHEMA
        exported = json.loads(Path(__file__).with_name("contract.schema.json").read_text())
        self.assertEqual(exported, SCHEMA)


if __name__ == "__main__":
    unittest.main()
