import unittest

from nakedagent.llm import OllamaError, chat


class TestHostValidation(unittest.TestCase):
    """devin review P2.7: --host is user-supplied, not model-controlled, but
    there's no reason to accept anything other than a real http(s) server."""

    def test_rejects_file_scheme(self):
        with self.assertRaises(OllamaError):
            chat([], "model", host="file:///etc/passwd")

    def test_rejects_scheme_less_string(self):
        with self.assertRaises(OllamaError):
            chat([], "model", host="not-a-url")

    def test_rejects_empty_netloc(self):
        with self.assertRaises(OllamaError):
            chat([], "model", host="http://")


if __name__ == "__main__":
    unittest.main()
