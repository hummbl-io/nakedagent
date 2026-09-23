import unittest
import urllib.error
from unittest.mock import patch

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


class TestNonJsonResponse(unittest.TestCase):
    """A 200 with a non-JSON body must surface as OllamaError, not escape as a
    raw JSONDecodeError traceback (JSONDecodeError is not a URLError subclass)."""

    @patch("urllib.request.urlopen")
    def test_non_json_response_raises_ollama_error(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = b"not json"
        with self.assertRaises(OllamaError):
            chat([], "model", host="http://localhost:11434")


class TestHttpErrorResponse(unittest.TestCase):
    """A non-2xx from Ollama (HTTPError, a URLError subclass) must be reported
    as an HTTP error, not mislabeled 'could not reach Ollama' -- the server
    answered, so the connection-reached message would mislead the operator
    into restarting Ollama instead of fixing the request (e.g. bad model)."""

    @patch("urllib.request.urlopen")
    def test_http_error_reports_status_not_connection(self, mock_urlopen):
        err = urllib.error.HTTPError(
            url="http://localhost:11434/api/chat",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None,
        )
        mock_urlopen.side_effect = err
        with self.assertRaises(OllamaError) as ctx:
            chat([], "model", host="http://localhost:11434")
        self.assertIn("HTTP 404", str(ctx.exception))
        self.assertNotIn("could not reach", str(ctx.exception))


class TestThinkingDisabled(unittest.TestCase):
    """Regression: qwen3.5 through nakedagent returned an empty reply because
    thinking mode consumed the response. The request must send think=false."""

    @patch("urllib.request.urlopen")
    def test_request_body_disables_thinking(self, mock_urlopen):
        import json

        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"message": {"content": "ok"}}'
        )
        self.assertEqual(chat([], "model", host="http://localhost:11434"), "ok")
        sent = json.loads(mock_urlopen.call_args[0][0].data)
        self.assertIs(sent["think"], False)


if __name__ == "__main__":
    unittest.main()
