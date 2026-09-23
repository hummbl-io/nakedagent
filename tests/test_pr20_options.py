"""PR20 provider option forwarding is retained in the composed driver."""

import tempfile
import unittest
from pathlib import Path

from nakedagent.driver import run_functional


class DriverOptionsTests(unittest.TestCase):
    def test_provider_options_reach_only_model_call(self):
        observed = []

        def model(_messages, _model, _host, **kwargs):
            observed.append(kwargs)
            return "done"

        with tempfile.TemporaryDirectory() as folder:
            state = run_functional(
                "go", "m", Path(folder), "h", tools={}, llm_fn=model,
                llm_options={"api": "fixture", "api_key_env": "UNSET_FIXTURE"},
            )
        self.assertTrue(state.is_terminal)
        self.assertEqual(observed, [{"api": "fixture", "api_key_env": "UNSET_FIXTURE"}])


if __name__ == "__main__":
    unittest.main()
