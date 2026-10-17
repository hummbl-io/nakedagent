"""Behavioral checks, including alternate requests beyond the scripted cases."""
import unittest

from e0 import Broker, Grant, experiment, propose


class PermissionEffects(unittest.TestCase):
    def ready(self, **grant):
        b = Broker()
        b.disturb()
        b.attach(Grant(**grant))
        return b

    def test_eight_conditions(self):
        report = experiment()
        self.assertEqual(len(report["results"]), 8)
        for row in report["results"]:
            with self.subTest(condition=row["condition"]):
                self.assertTrue(row["passed"], row)
                self.assertEqual([e["kind"] for e in row["events"]].count("attempt"), 3)

    def test_controller_both_directions_and_target(self):
        self.assertIsNone(propose(5, 0, 1))
        self.assertEqual(propose(8, 0, 1)["delta"], -1)
        self.assertEqual(propose(2, 0, 1)["delta"], 1)

    def test_execution_time_revocation(self):
        b = self.ready()
        request = propose(b.x, b.version, 1)
        b.revoke()  # Permission changed after proposal, before execution.
        self.assertEqual(b.dispatch(request), "revoked")
        self.assertEqual((b.x, b.used, b.version), (2, 0, 1))

    def test_expiry_boundary_and_clock_rollback(self):
        b = self.ready(expires=2)
        b.advance(1)
        self.assertEqual(b.dispatch(propose(b.x, b.version, 1)), "allowed")
        b.advance(2)
        self.assertEqual(b.dispatch(propose(b.x, b.version, 2)), "expired")
        with self.assertRaises(ValueError):
            b.advance(1)
        self.assertEqual(b.x, 3)

    def test_binding_and_malformed_requests_do_not_consume(self):
        changes = [{"experiment": "other"}, {"grant": "other"}, {"grant_version": 2},
                   {"sequence": 0}, {"sequence": True}, {"delta": 2}, {"action": "shell"},
                   {"expected_state_version": True}, {"extra": "authority"}]
        for change in changes:
            with self.subTest(change=change):
                b = self.ready()
                request = propose(b.x, b.version, 1)
                request.update(change)
                self.assertNotEqual(b.dispatch(request), "allowed")
                self.assertEqual((b.x, b.used, b.version), (2, 0, 1))
        for request in (None, [], {}, {"sequence": 1}):
            self.assertEqual(self.ready().dispatch(request), "malformed")

    def test_replay_payload_collision_and_detached_receipt(self):
        b = self.ready()
        request = propose(b.x, b.version, 1)
        self.assertEqual(b.dispatch(request), "allowed")
        request["delta"] = -1
        self.assertEqual(b.dispatch(request), "sequence_collision")
        self.assertEqual(b.events[2]["request"]["delta"], 1)
        self.assertEqual((b.x, b.used), (3, 1))

    def test_effect_order_and_bounds(self):
        b = self.ready()
        self.assertEqual(b.dispatch(propose(b.x, b.version, 1)), "allowed")
        self.assertEqual([e["kind"] for e in b.events[-4:]],
                         ["attempt", "decision", "reservation", "effect"])
        b.x = 10  # Trusted supervisor fixture, not a controller capability.
        request = propose(b.x, b.version, 2)
        request["delta"] = 1
        self.assertEqual(b.dispatch(request), "out_of_bounds")
        self.assertEqual((b.x, b.used), (10, 1))

    def test_reattachment_cannot_reset_budget_or_revocation(self):
        b = self.ready(budget=0)
        self.assertEqual(b.dispatch(propose(b.x, b.version, 1)), "budget_exhausted")
        b.revoke()
        with self.assertRaises(ValueError):
            b.attach(Grant())
        self.assertTrue(b.revoked)

    def test_invalid_supervisor_grants(self):
        for grant in (Grant(version=True), Grant(budget=True), Grant(budget=4),
                      Grant(expires=-1), Grant(evidence="yes"), Grant(experiment="other")):
            with self.subTest(grant=grant), self.assertRaises(ValueError):
                Broker().attach(grant)


if __name__ == "__main__":
    unittest.main()
