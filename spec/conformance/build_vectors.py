"""Regenerate spec/conformance/vectors/*.json from the Python reference.

Run on Linux (the shell-policy and POSIX word-splitting vectors are defined for
POSIX argv splitting):

    python3 spec/conformance/build_vectors.py

Inputs are authored here; expected results are recorded from the reference in
``reference_runner.py`` and then reviewed in the diff. A few expectations are
authored by hand and *checked* against the reference instead of recorded (large
truncation cases, error substrings, POSIX-only execution) so the reference is not
the only witness. ``tests/test_conformance_vectors.py`` re-runs every vector.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import reference_runner as rr  # noqa: E402

OUT = HERE / "vectors"


def R(s: str, n: int) -> dict:
    return {"repeat": [s, n]}


def C(*parts) -> dict:
    return {"concat": list(parts)}


def B(raw: bytes) -> dict:
    import base64

    return {"b64": base64.b64encode(raw).decode("ascii")}


# --------------------------------------------------------------------- cases

TOOLCALL = [
    ("single shell call", "```shell\nls -la\n```"),
    ("write with path argument", "```write a/b.txt\nhello\n```"),
    ("prose around a call", "I will list files.\n\n```shell\nls\n```\n\nDone."),
    ("two calls in order", "```read a.txt\n```\ntext\n```shell\npwd\n```"),
    ("no tool call in plain prose", "Nothing to run here."),
    ("no tool call for untagged fence", "```\nls\n```"),
    ("non-tool language tag is still dispatched", "```python\nprint(1)\n```"),
    ("uppercase tag keeps its casing", "```SHELL\nls\n```"),
    ("tag with digits and underscore", "```my_tool2 arg\nbody\n```"),
    ("args are trimmed", "```read    a.txt   \n```"),
    ("empty body", "```shell\n```"),
    ("multi-line body is joined with LF", "```write f\nline1\nline2\n\nline4\n```"),
    ("nested inner fence stays in body",
     "```write doc.md\nExample:\n```python\nprint('x')\n```\nEnd\n```"),
    ("nested shell example is not a second call",
     "```write doc.md\n```shell\nrm -rf /\n```\n```"),
    ("longer bare run inside body is not a close",
     "```write f\nbefore\n````\nafter\n```"),
    ("close allows trailing whitespace", "```shell\nls\n```   \nafter"),
    ("indented fence is not an opener", "  ```shell\nls\n  ```"),
    ("indented backticks in body are not a close", "```write f\n  ```\nstill body\n```"),
    ("opener args may not contain a backtick", "```write a`b\nbody\n```"),
    ("unclosed fence is refused", "```write f\nbody with no close"),
    ("unclosed fence swallows later calls into one refusal",
     "```write f\nbody\n```shell\nls\n"),
    ("a closed call survives and a later unclosed call is refused", "```read a\n```\n```write f\nx"),
    ("CRLF input is normalised to LF", "```write f\r\nline1\r\nline2\r\n```\r\n"),
    ("U+2028 is not a line break", "```write f\na ```shell\nb\n```"),
    ("form feed is not a line break", "```write f\na\x0c```\nb\n```"),
    ("unicode body preserved", "```write f\nhéllo \U0001f600\n```"),
]

PATCH_SPLIT = [
    ("simple block", "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"),
    ("multi-line search and replace",
     "<<<<<<< SEARCH\na\nb\n=======\nc\nd\ne\n>>>>>>> REPLACE"),
    ("empty replace deletes", "<<<<<<< SEARCH\nold\n=======\n>>>>>>> REPLACE"),
    ("empty search", "<<<<<<< SEARCH\n=======\nnew\n>>>>>>> REPLACE"),
    ("marker lines are matched after strip",
     "  <<<<<<< SEARCH  \nold\n  =======\nnew\n>>>>>>> REPLACE  "),
    ("blank lines after the block are allowed",
     "<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE\n\n  \n"),
    ("leading prose before the block is ignored",
     "intro\n<<<<<<< SEARCH\nold\n=======\nnew\n>>>>>>> REPLACE"),
    ("missing markers", "just text"),
    ("markers out of order", "=======\n<<<<<<< SEARCH\nx\n>>>>>>> REPLACE"),
    ("missing end marker", "<<<<<<< SEARCH\nold\n=======\nnew"),
    ("second start marker before the end is rejected",
     "<<<<<<< SEARCH\na\n=======\n<<<<<<< SEARCH\nb\n>>>>>>> REPLACE"),
    ("content after the block is rejected",
     "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\nextra"),
    ("a second full block after the first is rejected",
     "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nc\n=======\nd\n>>>>>>> REPLACE"),
    ("separator inside replace body is kept",
     "<<<<<<< SEARCH\na\n=======\nb\n=======\nc\n>>>>>>> REPLACE"),
    ("close marker must match fully", "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLAC"),
]

_PATCH_OK = "<<<<<<< SEARCH\nfoo\n=======\nbar\n>>>>>>> REPLACE"

FS = [
    # ---- read
    dict(name="read existing file", tool="read", args="a.txt", files={"a.txt": "hello\nworld\n"}),
    dict(name="read file in subdirectory", tool="read", args="d/e.txt", files={"d/e.txt": "x"}),
    dict(name="read args are trimmed", tool="read", args="  a.txt  ", files={"a.txt": "x"}),
    dict(name="read empty path", tool="read", args="", files={}),
    dict(name="read missing file", tool="read", args="nope.txt", files={}),
    dict(name="read directory lists sorted names", tool="read", args="d",
         files={"d/b.txt": "1", "d/a.txt": "2", "d/C.txt": "3", "d/sub/x": "4"}),
    dict(name="read outside workspace via dotdot", tool="read", args="../outside.txt", files={}),
    dict(name="read absolute path outside workspace", tool="read", args="/etc/hostname", files={}),
    dict(name="read invalid utf-8 is replaced not rejected", tool="read", args="bin.dat",
         files={"bin.dat": B(b"ok\xffend")}),
    dict(name="read truncates at 8000 characters", tool="read", args="big.txt",
         files={"big.txt": R("a", 8001)}),
    dict(name="read does not truncate at exactly 8000", tool="read", args="big.txt",
         files={"big.txt": R("a", 8000)}),
    dict(name="read truncation counts code points not bytes", tool="read", args="big.txt",
         files={"big.txt": R("\U0001f600", 8003)}),
    dict(name="read truncation counts code points for 2-byte chars", tool="read", args="big.txt",
         files={"big.txt": R("é", 8010)}),
    # ---- write
    dict(name="write new file", tool="write", args="out.txt", content="hello", files={}),
    dict(name="write creates parent directories", tool="write", args="a/b/c.txt", content="x", files={}),
    dict(name="write overwrites existing file", tool="write", args="a.txt", content="new", files={"a.txt": "old"}),
    dict(name="write empty path", tool="write", args="", content="x", files={}),
    dict(name="write outside workspace", tool="write", args="../x.txt", content="x", files={}),
    dict(name="write into .git is protected", tool="write", args=".git/config", content="x", files={}),
    dict(name="write into .nakedagent is protected", tool="write", args=".nakedagent/plugins/p.py",
         content="x", files={}),
    dict(name="write count is in code points", tool="write", args="u.txt",
         content="héllo \U0001f600", files={}),
    dict(name="write empty content", tool="write", args="e.txt", content="", files={}),
    dict(name="write path that merely contains .git is allowed", tool="write", args="a/.git/x",
         content="x", files={}),
    dict(name="write path starting with .github is allowed", tool="write", args=".github/ci.yml",
         content="x", files={}),
    # ---- patch
    dict(name="patch replaces unique match", tool="patch", args="f.txt", content=_PATCH_OK,
         files={"f.txt": "a\nfoo\nb\n"}),
    dict(name="patch multi-line search", tool="patch", args="f.txt",
         content="<<<<<<< SEARCH\nl1\nl2\n=======\nX\n>>>>>>> REPLACE", files={"f.txt": "l0\nl1\nl2\nl3\n"}),
    dict(name="patch can delete text", tool="patch", args="f.txt",
         content="<<<<<<< SEARCH\nfoo\n=======\n>>>>>>> REPLACE", files={"f.txt": "afoob"}),
    dict(name="patch search is exact including whitespace", tool="patch", args="f.txt",
         content="<<<<<<< SEARCH\nfoo \n=======\nbar\n>>>>>>> REPLACE", files={"f.txt": "foo\n"}),
    dict(name="patch no match", tool="patch", args="f.txt", content=_PATCH_OK, files={"f.txt": "zzz"}),
    dict(name="patch ambiguous match", tool="patch", args="f.txt", content=_PATCH_OK,
         files={"f.txt": "foo\nfoo\nfoo\n"}),
    dict(name="patch missing file", tool="patch", args="gone.txt", content=_PATCH_OK, files={}),
    dict(name="patch empty path", tool="patch", args="", content=_PATCH_OK, files={}),
    dict(name="patch malformed block", tool="patch", args="f.txt", content="no markers",
         files={"f.txt": "foo"}),
    dict(name="patch outside workspace", tool="patch", args="../f.txt", content=_PATCH_OK, files={}),
    dict(name="patch protected directory", tool="patch", args=".git/HEAD", content=_PATCH_OK,
         files={".git/HEAD": "foo"}),
    dict(name="patch refuses non-utf8 file and leaves it unchanged", tool="patch", args="b.bin",
         content=_PATCH_OK, files={"b.bin": B(b"foo\xff")}),
    dict(name="patch empty search matches many places", tool="patch", args="f.txt",
         content="<<<<<<< SEARCH\n=======\nX\n>>>>>>> REPLACE", files={"f.txt": "abc"}),
]

# Pure argv-prefix matching with POSIX word splitting.
ALLOWLIST = [
    ("exact command", "ls", ["ls"], True),
    ("prefix match with extra args", "git status -s", ["git status"], True),
    ("empty allowlist denies", "ls", [], False),
    ("blank pattern ignored", "ls", ["", "  "], False),
    ("non-matching pattern", "rm -rf x", ["git status"], False),
    ("shorter command than pattern", "git", ["git status"], False),
    ("semicolon glued to token does not match", "git status; rm -rf /", ["git status"], False),
    ("semicolon as its own token still matches the prefix", "git status ; rm -rf /", ["git status"], True),
    ("and-and glued", "git status&&rm x", ["git status"], False),
    ("command substitution is literal", "echo $(id)", ["echo hi"], False),
    ("any pattern may match", "ls -l", ["git status", "ls"], True),
    ("pattern is a token prefix not a string prefix", "lsof", ["ls"], False),
    ("single quotes group a token", "echo 'a b'", ["echo 'a b'"], True),
    ("unquoted pattern words do not match a quoted token", "echo 'a b'", ["echo a b"], False),
    ("double quotes group a token", 'echo "a b"', ["echo 'a b'"], True),
    ("backslash escapes a space outside quotes", "echo a\\ b", ["echo 'a b'"], True),
    ("backslash is literal inside single quotes", "echo 'a\\b'", ["echo a\\\\b"], True),
    ("escaped quote inside double quotes", 'echo "a\\"b"', ["echo 'a\"b'"], True),
    ("unbalanced quote in command denies", 'echo "abc', ["echo"], False),
    ("unbalanced quote in pattern is skipped", "ls", ['echo "abc', "ls"], True),
    ("unbalanced quote only pattern denies", "ls", ['echo "abc'], False),
    ("surrounding whitespace is ignored", "   ls   -l  ", ["ls"], True),
    ("empty command denies", "   ", ["ls"], False),
    ("hash is not a comment", "echo a # b", ["echo a #"], True),
    ("tabs separate tokens", "ls\t-l", ["ls -l"], True),
]

SHELL = [
    dict(name="no command", content="", args="", allow_shell=True, shell_allowlist=["ls"]),
    dict(name="whitespace-only command", content="   \n", args="", allow_shell=True, shell_allowlist=["ls"]),
    dict(name="non-positive timeout", content="ls", allow_shell=True, shell_allowlist=["ls"], shell_timeout=0),
    dict(name="negative timeout", content="ls", allow_shell=True, shell_allowlist=["ls"], shell_timeout=-5),
    dict(name="blocked without allow_shell", content="ls", allow_shell=False, shell_allowlist=["ls"]),
    dict(name="blocked without allow_shell and no allowlist", content="ls", allow_shell=False),
    dict(name="allow_shell but empty allowlist", content="ls", allow_shell=True, shell_allowlist=[]),
    dict(name="allow_shell but not in allowlist", content="rm -rf x", allow_shell=True,
         shell_allowlist=["ls"]),
    dict(name="chained command not in allowlist", content="ls; rm -rf x", allow_shell=True,
         shell_allowlist=["ls"]),
    dict(name="malformed quoting is blocked by the allowlist check", content='echo "abc',
         allow_shell=True, shell_allowlist=["echo"]),
    dict(name="program not on PATH", content="nakedagent-no-such-program-zzz", allow_shell=True,
         shell_allowlist=["nakedagent-no-such-program-zzz"]),
    dict(name="command taken from args when body is empty", content="", args="nakedagent-no-such-program-zzz",
         allow_shell=True, shell_allowlist=["nakedagent-no-such-program-zzz"]),
]

# Authored by hand (POSIX only); checked against the reference, not recorded.
SHELL_POSIX_EXEC = [
    (dict(name="runs an allowed command and reports exit code and stdout", content="echo hi",
          allow_shell=True, shell_allowlist=["echo"]), "(exit 0)\nhi\n"),
    (dict(name="metacharacters are literal arguments, not operators", content="echo a; echo b",
          allow_shell=True, shell_allowlist=["echo"]), "(exit 0)\na; echo b\n"),
    (dict(name="nonzero exit code is reported", content="false",
          allow_shell=True, shell_allowlist=["false"]), "(exit 1)"),
    (dict(name="stderr is appended under a separator", content="sh -c 'echo out; echo err 1>&2; exit 3'",
          allow_shell=True, shell_allowlist=["sh -c"]),
     "(exit 3)\nout\n\n--- stderr ---\nerr\n"),
    (dict(name="timeout is reported", content="sleep 5",
          allow_shell=True, shell_allowlist=["sleep"], shell_timeout=1),
     "Error: command timed out after 1s."),
    (dict(name="output is truncated at 8000 characters", content="sh -c 'head -c 9000 /dev/zero | tr \"\\\\0\" a'",
          allow_shell=True, shell_allowlist=["sh -c"]),
     C("(exit 0)\n", R("a", 7991), "\n...[truncated, 1009 more chars]")),
]

PROMPT = [
    dict(name="default four tools"),
    dict(name="tools without usage are listed by name, sorted",
         extra_tools_without_usage=["zeta", "alpha"]),
]

ENV_KEY = {"OPENAI_API_KEY": "sk-test-1"}
MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
OK_OLLAMA = {"status": 200, "body": {"message": {"content": "hello there"}}}
OK_OPENAI = {"status": 200, "body": {"choices": [{"message": {"content": "hello there"}}]}}

LLM = [
    dict(name="ollama request shape and reply", api="ollama", model="m1", messages=MSGS,
         server=[OK_OLLAMA]),
    dict(name="ollama never sends credentials even if the env var is set", api="ollama", model="m1",
         messages=MSGS, env=ENV_KEY, server=[OK_OLLAMA]),
    dict(name="openai request shape, path and bearer key", api="openai", model="gpt-x", messages=MSGS,
         env=ENV_KEY, host_path="/v1", server=[OK_OPENAI]),
    dict(name="openai trailing slash on host is normalised", api="openai", model="gpt-x", messages=MSGS,
         host_path="/v1/", server=[OK_OPENAI]),
    dict(name="openai without a key sends no Authorization header", api="openai", model="gpt-x",
         messages=MSGS, host_path="/v1", server=[OK_OPENAI]),
    dict(name="openai custom key variable", api="openai", model="gpt-x", messages=MSGS,
         api_key_env="CUSTOM_KEY", env={"CUSTOM_KEY": "custom-secret"}, host_path="/v1",
         server=[OK_OPENAI]),
    dict(name="openai null content becomes empty string", api="openai", model="gpt-x", messages=MSGS,
         host_path="/v1", server=[{"status": 200, "body": {"choices": [{"message": {"content": None}}]}}]),
    dict(name="ollama missing message field", api="ollama", model="m1", messages=MSGS,
         server=[{"status": 200, "body": {"nope": 1}}],
         error_contains=["unexpected Ollama response shape"]),
    dict(name="openai empty choices", api="openai", model="gpt-x", messages=MSGS, host_path="/v1",
         server=[{"status": 200, "body": {"choices": []}}],
         error_contains=["unexpected OpenAI-compatible API response shape"]),
    dict(name="http 500 with body", api="ollama", model="m1", messages=MSGS,
         server=[{"status": 500, "body": "boom"}],
         error_contains=["Ollama at http://HOST:PORT returned HTTP 500", ": boom"]),
    dict(name="http 401 on openai hints at the key variable", api="openai", model="gpt-x", messages=MSGS,
         host_path="/v1", server=[{"status": 401, "body": "nope"}],
         error_contains=["returned HTTP 401", "(check the key in $OPENAI_API_KEY)"]),
    dict(name="http 403 on openai hints at the custom key variable", api="openai", model="gpt-x",
         messages=MSGS, api_key_env="CUSTOM_KEY", host_path="/v1",
         server=[{"status": 403, "body": "no"}],
         error_contains=["returned HTTP 403", "(check the key in $CUSTOM_KEY)"]),
    dict(name="http 401 on ollama has no key hint", api="ollama", model="m1", messages=MSGS,
         server=[{"status": 401, "body": "no"}], error_contains=["returned HTTP 401"],
         error_absent=["check the key"]),
    dict(name="200 with a non-json body", api="ollama", model="m1", messages=MSGS,
         server=[{"status": 200, "body": "<html>proxy error</html>"}],
         error_contains=["returned a non-JSON response"]),
    dict(name="connection refused (ollama)", api="ollama", model="m1", messages=MSGS, unreachable=True,
         error_contains=["could not reach Ollama at http://HOST:PORT", "Is `ollama serve` running?"]),
    dict(name="connection refused (openai)", api="openai", model="gpt-x", messages=MSGS, unreachable=True,
         error_contains=["could not reach OpenAI-compatible API at http://HOST:PORT"],
         error_absent=["ollama serve"]),
    dict(name="host scheme must be http or https", api="ollama", model="m1", messages=MSGS,
         host="file:///etc/passwd",
         error_contains=["--host must be an http:// or https:// URL, got: 'file:///etc/passwd'"]),
    dict(name="host must have a network location", api="ollama", model="m1", messages=MSGS,
         host="http://", error_contains=["--host must be an http:// or https:// URL"]),
    dict(name="unknown api is rejected", api="bogus", model="m1", messages=MSGS, host="http://localhost:1",
         error_contains=["--api must be one of ollama, openai, got: 'bogus'"]),
    dict(name="credentials are not forwarded across a redirect", api="openai", model="gpt-x",
         messages=MSGS, env=ENV_KEY, host_path="/v1",
         server=[{"status": 302, "headers": {"Location": "/final"}, "body": ""}, OK_OPENAI],
         lenient_requests=True),
]


def tool_reply(tool: str, args: str = "", body: str = "") -> str:
    return f"```{tool}{(' ' + args) if args else ''}\n{body}\n```" if body else f"```{tool}{(' ' + args) if args else ''}\n```"


LOOP = [
    dict(name="no tool call ends after one request", prompt="hi", replies=["just text"], files={}),
    dict(name="one tool round then a final answer", prompt="read it",
         replies=[tool_reply("read", "a.txt"), "done"], files={"a.txt": "contents"}),
    dict(name="write then read back", prompt="go",
         replies=[tool_reply("write", "n.txt", "new"), tool_reply("read", "n.txt"), "ok"], files={}),
    dict(name="unknown tool is reported to the model", prompt="go",
         replies=[tool_reply("frobnicate", "", "x"), "ok"], files={}),
    dict(name="tool name lookup is case-insensitive but output keeps the casing", prompt="go",
         replies=[tool_reply("READ", "a.txt"), "ok"], files={"a.txt": "x"}),
    dict(name="several calls in one reply all run before the next request", prompt="go",
         replies=[tool_reply("read", "a.txt") + "\n" + tool_reply("read", "b.txt"), "ok"],
         files={"a.txt": "A", "b.txt": "B"}),
    dict(name="shell is blocked without allow_shell", prompt="go",
         replies=[tool_reply("shell", "", "ls"), "ok"], files={}),
    dict(name="round cap hands control back after 25 rounds", prompt="loop forever",
         replies=[tool_reply("read", "a.txt")] * 30, files={"a.txt": "x"}),
]


# --------------------------------------------------------------------- build

def _llm_expect(case: dict, actual: dict) -> dict:
    exp: dict = {"requests": actual["requests"]}
    if "error_contains" in case:
        if "error" not in actual:
            raise SystemExit(f"{case['name']}: expected an error, got {actual}")
        for sub in case["error_contains"]:
            if sub not in actual["error"]:
                raise SystemExit(f"{case['name']}: {sub!r} not in {actual['error']!r}")
        for sub in case.get("error_absent", []):
            if sub in actual["error"]:
                raise SystemExit(f"{case['name']}: {sub!r} unexpectedly in {actual['error']!r}")
        exp["error_contains"] = case["error_contains"]
        if "error_absent" in case:
            exp["error_absent"] = case["error_absent"]
    else:
        if "reply" not in actual:
            raise SystemExit(f"{case['name']}: expected a reply, got {actual}")
        exp["reply"] = actual["reply"]
    return exp


def build() -> None:
    OUT.mkdir(exist_ok=True)

    def dump(name: str, doc: dict) -> None:
        (OUT / f"{name}.json").write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )

    # toolcall
    cases = [{"name": n, "input": i, "expect": rr.run_toolcall({"input": i})} for n, i in TOOLCALL]
    dump("toolcall", {"suite": "toolcall", "cases": cases})

    # patch_split
    cases = [{"name": n, "input": i, "expect": rr.run_patch_split({"input": i})} for n, i in PATCH_SPLIT]
    dump("patch_split", {"suite": "patch_split", "cases": cases})

    # fs_tools
    cases = []
    for c in FS:
        c = dict(c)
        c["expect"] = rr.run_fs(c)
        cases.append(c)
    dump("fs_tools", {"suite": "fs_tools", "cases": cases})

    # shell_allowlist
    cases = []
    for n, cmd, al, want in ALLOWLIST:
        got = rr.run_allowlist({"command": cmd, "allowlist": al})
        if got != want:
            print(f"MISMATCH allowlist {n!r}: authored {want}, reference says {got}")
            continue
        cases.append({"name": n, "command": cmd, "allowlist": al, "expect": want})
    dump("shell_allowlist", {"suite": "shell_allowlist", "requires": "posix", "cases": cases})

    # shell_policy
    cases = []
    for c in SHELL:
        c = dict(c)
        c["expect"] = rr.run_shell(c)
        cases.append(c)
    for c, want in SHELL_POSIX_EXEC:
        c = dict(c)
        got = rr.run_shell(c)
        if rr.decode_text(got) != rr.decode_text(want):
            raise SystemExit(f"shell {c['name']!r}: authored {want!r}, reference says {got!r}")
        c["expect"] = want
        c["requires"] = "posix"
        cases.append(c)
    dump("shell_policy", {"suite": "shell_policy", "cases": cases})

    # prompt
    cases = []
    for c in PROMPT:
        c = dict(c)
        c["expect"] = rr.run_prompt(c)
        cases.append(c)
    dump("prompt", {"suite": "prompt", "cases": cases})

    # llm_wire
    cases = []
    for c in LLM:
        c = dict(c)
        actual = rr.run_llm(c)
        c["expect"] = _llm_expect(c, actual)
        if c.get("lenient_requests"):
            # Redirect handling is not mandated (a port may refuse to follow); only the
            # first request is exact and no later request may carry credentials.
            c["expect"] = {"first_request": actual["requests"][0], "later_requests_have_no_authorization": True}
        c.pop("error_contains", None)
        c.pop("error_absent", None)
        cases.append(c)
    dump("llm_wire", {"suite": "llm_wire", "cases": cases})

    # loop
    cases = []
    for c in LOOP:
        c = dict(c)
        c["expect"] = rr.run_loop(c)
        cases.append(c)
    dump("loop", {"suite": "loop", "cases": cases})


if __name__ == "__main__":
    build()
    print("vectors written to", OUT)
