"""CO16: System Integration Testing — assembled lab gates, not OS containment."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from composition import ComposedLabBroker, audit_chain, compile_loadout, evidence_record
from contract import VERSION, digest


def setup_lab(folder, kernel=None, principal="lab-worker"):
    folder = Path(folder)
    fixture = folder / "public.txt"
    fixture.write_bytes(b"public test fixture\n")
    source = folder / "enrollment.txt"
    source.write_bytes(b"synthetic enrollment observation\n")
    artifacts = {name: Path(__file__).with_name(name) for name in
                 ["contract.py", "admission_pilot.py", "composition.py"]}
    components = [{"id": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                   "dependencies": ["contract.py"] if name != "contract.py" else []}
                  for name, path in artifacts.items()]
    configuration = digest({"profile": "composition-lab", "effects": ["read_fixture"]})
    graph = digest(compile_loadout(components))
    contract = {"schema": VERSION, "run_id": "composed-lab", "principal": principal,
                "policy_sha256": digest({"policy": "fixed-read-lab"}),
                "configuration_sha256": configuration, "dependency_graph_sha256": graph,
                "components": components, "required_evidence": ["fixture-enrollment"],
                "grants": [{"operation": "read_fixture", "resource": "lab:public-fixture"}],
                "max_actions": 2, "expires_at": 200}
    cer = evidence_record(source_bytes=source.read_bytes(), configuration_sha256=configuration,
                          loadout_sha256=graph, observed_at=90, expires_at=150)
    calls = []

    def default_kernel(action):
        calls.append(action)
        return {"decision": "allow", "required_controls": [], "enforcement_status": "test-double"}

    kwargs = {"owner_grant_sha256": digest(contract), "fixture": fixture,
              "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(), "artifacts": artifacts,
              "configuration_sha256": configuration, "graph_sha256": graph,
              "kernel": kernel or default_kernel, "clock": lambda: 100, "cer": cer, "source": source}
    action = {"action_id": "a1", "run_id": contract["run_id"], "principal": principal,
              "contract_sha256": digest(contract), "operation": "read_fixture", "resource": "lab:public-fixture"}
    return contract, kwargs, action, calls


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.contract, self.kwargs, self.action, self.calls = setup_lab(self.temp.name)

    def broker(self):
        return ComposedLabBroker(self.contract, **self.kwargs)

    def test_full_composition_and_receipt_linkage(self):
        lab = self.broker()
        result = lab.dispatch(self.action)
        self.assertEqual(result["decision"], "completed")
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(audit_chain(lab.chain.records, result["receipt_sha256"]))
        kinds = [r["kind"] for r in lab.chain.records]
        self.assertEqual(kinds, ["loadout", "source-evidence", "kernel-request", "kernel-response",
                                 "broker-event", "broker-event"])
        self.assertEqual(lab.chain.records[3]["data"]["request_sha256"], lab.chain.records[2]["sha256"])
        lab.export(Path(self.temp.name)/"receipts.json")

    def test_unresolved_and_cyclic_dependencies_rejected_before_kernel(self):
        for dep in ["missing.py", "composition.py"]:
            with self.subTest(dep=dep):
                components = copy.deepcopy(self.contract["components"])
                next(c for c in components if c["id"] == "composition.py")["dependencies"] = [dep]
                with self.assertRaises(ValueError):
                    compile_loadout(components)
        self.assertEqual(self.calls, [])

    def test_new_appendage_is_not_loaded_and_blocks_dispatch(self):
        lab = self.broker()
        marker = Path(self.temp.name)/"executed"
        plugin = Path(self.temp.name)/"unadmitted.py"
        plugin.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
        lab.artifacts["unadmitted.py"] = plugin
        self.assertEqual(lab.dispatch(self.action)["decision"], "deny")
        self.assertFalse(marker.exists())
        self.assertEqual(self.calls, [])

    def test_expiry_blocks_second_effect_without_second_kernel_call(self):
        lab = self.broker()
        self.assertEqual(lab.dispatch(self.action)["decision"], "completed")
        lab.clock = lambda: 150
        self.assertEqual(lab.dispatch({**self.action, "action_id": "a2"})["decision"], "require_more_evidence")
        self.assertEqual(lab.used, 1)
        self.assertEqual(len(self.calls), 1)

    def test_expiry_during_kernel_callback_blocks_effect(self):
        lab = self.broker()
        original = lab.kernel

        def delayed(action):
            result = original(action)
            lab.clock = lambda: 150
            return result

        lab.kernel = delayed
        self.assertEqual(lab.dispatch(self.action)["decision"], "require_more_evidence")
        self.assertEqual(lab.used, 0)

    def test_source_drift_holds_before_kernel(self):
        lab = self.broker()
        self.kwargs["source"].write_bytes(b"replacement observation")
        self.assertEqual(lab.dispatch(self.action)["reasons"], ["source_drift"])
        self.assertEqual(self.calls, [])

    def test_irrelevant_or_forged_evidence_not_authority(self):
        for field, value in [("subject", "lab:another-resource"), ("collector", "unregistered"),
                             ("configuration_sha256", "0"*64), ("observed_at", 101)]:
            with self.subTest(field=field):
                kwargs = copy.deepcopy(self.kwargs)
                kwargs["cer"][field] = value
                lab = ComposedLabBroker(self.contract, **kwargs)
                self.assertEqual(lab.dispatch(self.action)["decision"], "require_more_evidence")
                self.assertEqual(lab.used, 0)

    def test_kernel_denial_and_revocation_preserved(self):
        lab = self.broker()
        lab.kernel = lambda _: {"decision": "deny", "required_controls": []}
        self.assertEqual(lab.dispatch(self.action)["decision"], "deny")
        lab = self.broker()
        lab.revoked = True
        self.assertEqual(lab.dispatch(self.action)["decision"], "deny")
        self.assertEqual(lab.used, 0)

    def test_receipt_tampering_and_truncation_detected_with_checkpoint(self):
        lab = self.broker()
        lab.dispatch(self.action)
        changed = copy.deepcopy(lab.chain.records)
        changed[1]["data"]["subject"] = "forged"
        for records in [changed, lab.chain.records[:-1], list(reversed(lab.chain.records))]:
            with self.assertRaises(ValueError):
                audit_chain(records, lab.chain.checkpoint)

    def test_evidence_mutation_after_enrollment_holds(self):
        lab = self.broker()
        lab.cer["expires_at"] = 199
        self.assertEqual(lab.dispatch(self.action)["decision"], "require_more_evidence")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
