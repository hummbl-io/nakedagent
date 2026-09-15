import unittest
import urllib.error
from unittest.mock import patch

from nakedagent.llm import LLMError, OllamaError, chat


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


def _reply(mock_urlopen, body: bytes) -> None:
    mock_urlopen.return_value.__enter__.return_value.read.return_value = body


class TestOpenAICompatible(unittest.TestCase):
    """--api openai reaches hosted and self-hosted models too large to run
    locally. The wire format differs from Ollama's; the error contract doesn't."""

    @patch.dict("os.environ", {"NA_TEST_KEY": "sk-test-xxxx"})
    @patch("urllib.request.urlopen")
    def test_request_shape_and_auth(self, mock_urlopen):
        _reply(mock_urlopen, b'{"choices": [{"message": {"content": "hi"}}]}')
        out = chat(
            [{"role": "user", "content": "x"}],
            "big-model",
            host="https://api.example.com/v1/",
            api="openai",
            api_key_env="NA_TEST_KEY",
        )
        self.assertEqual(out, "hi")
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.example.com/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-test-xxxx")

    @patch.dict("os.environ", {}, clear=True)
    @patch("urllib.request.urlopen")
    def test_no_key_sends_no_auth_header(self, mock_urlopen):
        # Local OpenAI-compatible servers (vLLM, LM Studio, Ollama /v1) need none.
        _reply(mock_urlopen, b'{"choices": [{"message": {"content": "hi"}}]}')
        chat([], "m", host="http://localhost:8000/v1", api="openai")
        self.assertIsNone(mock_urlopen.call_args[0][0].get_header("Authorization"))

    @patch("urllib.request.urlopen")
    def test_null_content_becomes_empty_string(self, mock_urlopen):
        _reply(mock_urlopen, b'{"choices": [{"message": {"content": null}}]}')
        self.assertEqual(chat([], "m", host="http://h/v1", api="openai"), "")

    @patch("urllib.request.urlopen")
    def test_error_body_shape_raises(self, mock_urlopen):
        _reply(mock_urlopen, b'{"error": {"message": "bad"}}')
        with self.assertRaises(LLMError):
            chat([], "m", host="http://h/v1", api="openai")

    @patch("urllib.request.urlopen")
    def test_401_names_the_key_variable(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://h/v1/chat/completions", code=401, msg="Unauthorized", hdrs=None, fp=None
        )
        with self.assertRaises(LLMError) as ctx:
            chat([], "m", host="http://h/v1", api="openai", api_key_env="MY_KEY")
        self.assertIn("$MY_KEY", str(ctx.exception))

    def test_unknown_api_rejected(self):
        with self.assertRaises(LLMError):
            chat([], "m", api="anthropic")

    def test_ollama_error_alias_still_catches(self):
        self.assertIs(OllamaError, LLMError)


if __name__ == "__main__":
    unittest.main()
