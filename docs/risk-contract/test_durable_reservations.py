"""Restart and contention tests; no claim of power-loss or hostile-host resilience."""
import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from contract import digest
from durable_reservations import Reservations


class DurableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"state.sqlite"
        self.contract = {"max_actions": 1, "fixture": "public"}
        self.action = {"action_id": "one", "contract_sha256": digest(self.contract)}
        self.store = Reservations(self.path, self.contract, create=True)

    def test_reopen_keeps_budget_and_replay(self):
        self.assertIsNone(self.store.reserve(self.action))
        self.store.finish(self.action, {"decision": "completed"})
        reopened = Reservations(self.path, self.contract)
        self.assertEqual(reopened.reserve(self.action), "durable_replay")
        self.assertEqual(reopened.reserve({**self.action, "action_id": "two"}), "durable_budget_exhausted")

    def test_crash_reservation_remains_indeterminate(self):
        script = ("import json,os,sys; from durable_reservations import Reservations; "
                  "s=Reservations(sys.argv[1],json.loads(sys.argv[2])); "
                  "assert s.reserve(json.loads(sys.argv[3])) is None; os._exit(77)")
        result = subprocess.run([sys.executable, "-c", script, str(self.path), json.dumps(self.contract),
                                 json.dumps(self.action)], cwd=Path(__file__).parent, timeout=15, check=False)
        self.assertEqual(result.returncode, 77)
        reopened = Reservations(self.path, self.contract)
        self.assertEqual(reopened.snapshot()["actions"][0]["status"], "indeterminate")
        self.assertEqual(reopened.reserve(self.action), "durable_replay")

    def test_revocation_survives_reopen(self):
        self.store.revoke()
        self.assertEqual(Reservations(self.path, self.contract).reserve(self.action), "durably_revoked")

    def test_crash_after_simulated_effect_does_not_authorize_retry(self):
        marker = Path(self.temp.name)/"effect-marker.txt"
        script = ("import json,os,sys; from pathlib import Path; from durable_reservations import Reservations; "
                  "s=Reservations(sys.argv[1],json.loads(sys.argv[2])); "
                  "assert s.reserve(json.loads(sys.argv[3])) is None; "
                  "Path(sys.argv[4]).write_text('simulated effect completed'); os._exit(78)")
        result = subprocess.run([sys.executable, "-c", script, str(self.path), json.dumps(self.contract),
                                 json.dumps(self.action), str(marker)], cwd=Path(__file__).parent,
                                timeout=15, check=False)
        self.assertEqual(result.returncode, 78)
        self.assertTrue(marker.is_file())
        reopened = Reservations(self.path, self.contract)
        self.assertEqual(reopened.snapshot()["actions"][0]["status"], "indeterminate")
        self.assertEqual(reopened.reserve(self.action), "durable_replay")

    def test_missing_storage_does_not_initialize(self):
        with self.assertRaises(sqlite3.OperationalError):
            Reservations(Path(self.temp.name)/"missing.sqlite", self.contract)

    def test_create_refuses_existing_and_contract_mismatch(self):
        with self.assertRaises(FileExistsError):
            Reservations(self.path, self.contract, create=True)
        with self.assertRaises(ValueError):
            Reservations(self.path, {"max_actions": 2, "fixture": "public"})

    def test_concurrent_instances_cannot_double_spend(self):
        def reserve(i):
            return Reservations(self.path, self.contract).reserve({**self.action, "action_id": str(i)})
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(reserve, range(6)))
        self.assertEqual(results.count(None), 1)
        self.assertEqual(results.count("durable_budget_exhausted"), 5)

    def test_action_collision_and_double_finalization_rejected(self):
        self.store.reserve(self.action)
        changed = copy.deepcopy(self.action)
        changed["resource"] = "different"
        self.assertEqual(self.store.reserve(changed), "action_id_collision")
        self.store.finish(self.action, {"decision": "deny"})
        with self.assertRaises(ValueError):
            self.store.finish(self.action, {"decision": "completed"})


if __name__ == "__main__":
    unittest.main()
