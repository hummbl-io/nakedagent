"""Controller safety tests: no paid tool calls."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import pilot2_controller as controller


class ControllerSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.art = Path(self.temp.name)
        self.patch = patch.object(controller, "ART", self.art)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        (self.art / "preflight-expiry.json").write_text(json.dumps({"sandboxes": [
            {"name": "nakedagent-p2-preflight", "status": "stopped", "image": controller.IMAGE}]}))
        (self.art / "billing-baseline.json").write_text(json.dumps({
            "available_credit_usd": "249.99", "xl_rate_per_second_usd": "0.00031111"}))

    def test_budget_rejects_before_creation(self):
        with patch.object(controller, "RATE", Decimal("1")), patch.object(controller, "call") as call:
            with self.assertRaisesRegex(RuntimeError, "budget"):
                controller.main()
            call.assert_not_called()

    def test_existing_name_never_reused(self):
        with patch.object(controller, "state", return_value={"status": "stopped"}), patch.object(controller, "call") as call:
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                controller.main()
            call.assert_not_called()

    def test_lock_blocks_second_controller(self):
        (self.art / "controller.lock").write_text("prior attempt")
        with patch.object(controller, "call") as call:
            with self.assertRaises(FileExistsError):
                controller.main()
            call.assert_not_called()

    def test_export_timeout_still_stops_and_never_recreates(self):
        running = {"status": "running", "cpus": 16, "memory_mib": 32768, "image": controller.IMAGE,
                   "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        calls = []

        def fake(*args, **kwargs):
            calls.append(args)
            if args[0] == "cp":
                raise subprocess.TimeoutExpired("sbx", 90)
            return subprocess.CompletedProcess(args, 0, "DENY **", "")

        with patch.object(controller, "state", side_effect=[None, running, running, {"status": "stopped"}]), patch.object(controller, "call", side_effect=fake):
            self.assertEqual(controller.main(), 1)
        self.assertEqual(sum(c[0] == "create" for c in calls), 1)
        self.assertEqual(sum(c[0] == "stop" for c in calls), 1)
        result = json.loads((self.art / "controller-final.json").read_text())
        self.assertEqual(result["state"]["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
