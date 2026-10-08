"""Check the committed language-neutral conformance vectors against this implementation.

The vectors (spec/conformance/vectors/*.json) are the contract that every nakedagent
port must pass. They are recorded from this Python reference by
spec/conformance/build_vectors.py; this test keeps the two from drifting apart.
"""

import json
import os
import sys
import unittest
from pathlib import Path

CONF = Path(__file__).resolve().parents[1] / "spec" / "conformance"
sys.path.insert(0, str(CONF))

import reference_runner as rr  # noqa: E402

VECTORS = CONF / "vectors"
POSIX_ONLY_SUITES = {"shell_allowlist", "shell_policy"}


def canon(x):
    """Resolve the vector value encoding so expected and actual compare as plain data."""
    if isinstance(x, dict):
        if "repeat" in x or "concat" in x:
            return rr.decode_text(x)
        if "b64" in x and len(x) == 1:
            return ("bytes", x["b64"])
        return {k: canon(v) for k, v in x.items()}
    if isinstance(x, list):
        return [canon(v) for v in x]
    return x


def _check_llm(test, case, actual):
    exp = case["expect"]
    if case.get("lenient_requests"):
        test.assertEqual(canon(exp["first_request"]), actual["requests"][0])
        for later in actual["requests"][1:]:
            test.assertIsNone(later["authorization"])
        return
    test.assertEqual(exp["requests"], actual["requests"])
    if "reply" in exp:
        test.assertEqual(exp["reply"], actual.get("reply"), actual)
    else:
        err = actual.get("error")
        test.assertIsNotNone(err, f"expected an error, got {actual}")
        for sub in exp["error_contains"]:
            test.assertIn(sub, err)
        for sub in exp.get("error_absent", []):
            test.assertNotIn(sub, err)


def _make(suite_name, case):
    def test(self):
        if os.name == "nt" and (
            suite_name in POSIX_ONLY_SUITES or case.get("requires") == "posix"
        ):
            self.skipTest("POSIX-only vector")
        actual = rr.SUITES[suite_name](case)
        if suite_name == "llm_wire":
            _check_llm(self, case, actual)
        else:
            self.assertEqual(canon(case["expect"]), canon(actual))

    return test


def _load():
    for path in sorted(VECTORS.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        suite = doc["suite"]
        cls = type(f"TestConformance_{suite}", (unittest.TestCase,), {})
        for i, case in enumerate(doc["cases"]):
            slug = "".join(ch if ch.isalnum() else "_" for ch in case["name"])[:60]
            setattr(cls, f"test_{i:02d}_{slug}", _make(suite, case))
        globals()[cls.__name__] = cls


_load()


class TestVectorFiles(unittest.TestCase):
    def test_every_suite_has_a_runner_and_cases(self):
        names = {json.loads(p.read_text(encoding="utf-8"))["suite"] for p in VECTORS.glob("*.json")}
        self.assertEqual(names, set(rr.SUITES))
        for p in VECTORS.glob("*.json"):
            self.assertTrue(json.loads(p.read_text(encoding="utf-8"))["cases"], p.name)


if __name__ == "__main__":
    unittest.main()
