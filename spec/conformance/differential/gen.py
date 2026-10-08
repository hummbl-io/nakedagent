"""Generate seeded random inputs for differential testing of ports against the Python reference.

    python3 gen.py COUNT SEED > cases.jsonl

One JSON object per line, each with an "op":

  toolcall     {"input"}                 parse tool calls
  patch_split  {"input"}                 split a SEARCH/REPLACE block
  allowlist    {"cmd", "allowlist"}      shell allowlist match (POSIX word splitting)
  strip        {"input"}                 Python str.strip() whitespace rules
  decode       {"b64"}                   bytes.decode("utf-8", errors="replace")
  trunc        {"unit", "n"}             output truncation of unit * n (code point counting)

The inputs are built from tokens that are hard for parsers: fences of several lengths, CRLF and lone CR,
U+2028, form feed, NEL, quotes, backslashes, truncated multibyte sequences. Structured generators keep
a good share of the inputs valid enough to reach the interesting branches.
"""

import base64
import json
import random
import sys

rnd = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
N = int(sys.argv[1])

NL = ["\n", "\n", "\n", "\r\n"]
BODY = [
    "x", "print(1)", "", " ", "  indented", "é\U0001f600", "a b", "a\x0cb", "a\x85b", "`", "``", "`x`",
    "```python", "```", "````", "`````", "  ```", "```  ", "```\t", "```shell", "```write q", "```SHELL x", "```a`b",
    "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE",
]
TOOLS = ["shell", "read", "write", "patch", "SHELL", "Read", "my_tool2", "x", "python", "a-b", "", "w r"]
ARGS = ["", " a.txt", "  a/b.txt  ", " x`y", " é", "\t", " a b c", "  "]
WS = [
    " ", "\t", "\n", "\r", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\xa0", " ", "᠎", " ",
    " ", "​", " ", " ", " ", " ", "　", "﻿", "a", "b", "é",
]
BYTES = [
    0x41, 0x7F, 0x80, 0xBF, 0xC0, 0xC1, 0xC2, 0xDF, 0xE0, 0xA0, 0xE1, 0xE2, 0x82, 0xAC, 0xED, 0x9F, 0xA1, 0xEF, 0xF0,
    0x90, 0x9F, 0x98, 0xF1, 0xF4, 0x8F, 0xF5, 0xFF, 0x0A,
]
WORDS = [
    "git", "status", "ls", "-l", "a b", "$(id)", ";", "#", "é", "x y", "--flag=1", "'q r'", '"s t"', "a\\ b",
    '"a\\"b"', "'", '"', "\\", "'a\\b'", "''", '""', "\t",
]


def toolcall():
    parts = []
    for _ in range(rnd.randint(0, 4)):
        if rnd.random() < 0.5:
            parts.append(rnd.choice(["I will run it.", "", "text", "  ```shell", "``` ", "x```"]))
        parts.append("```" + rnd.choice(TOOLS) + rnd.choice(ARGS))
        parts.extend(rnd.choice(BODY) for _ in range(rnd.randint(0, 5)))
        if rnd.random() < 0.85:
            parts.append(rnd.choice(["```", "```", "```", "```  ", "````", "``"]))
    nl = rnd.choice(NL)
    return nl.join(parts) + rnd.choice(["", nl])


def patch_split():
    lines = ["old", "new", "", " ", "a b", " ", "x\fy", "\x85", "\x1c"]
    search = [rnd.choice(lines) for _ in range(rnd.randint(0, 3))]
    replace = [rnd.choice(lines) for _ in range(rnd.randint(0, 3))]
    parts = [rnd.choice(["", "intro", "  "])] if rnd.random() < 0.3 else []
    parts += [rnd.choice(["<<<<<<< SEARCH", "  <<<<<<< SEARCH  "])] + search
    parts += [rnd.choice(["=======", "  =======", "======= "])] + replace
    if rnd.random() < 0.15:
        parts += ["<<<<<<< SEARCH"]
    parts += [rnd.choice([">>>>>>> REPLACE", ">>>>>>> REPLACE", "  >>>>>>> REPLACE ", ">>>>>>> REPLAC", "======="])]
    if rnd.random() < 0.3:
        parts += [rnd.choice(["", "  ", "extra", " ", "\x85"])]
    if rnd.random() < 0.1:
        parts += ["<<<<<<< SEARCH", "a", "=======", "b", ">>>>>>> REPLACE"]
    return rnd.choice(["\n", "\r\n", "\r", "\n", "\n"]).join(parts)


def command():
    sep = rnd.choice([" ", " ", "  ", "\t"])
    return sep.join(rnd.choice(WORDS) for _ in range(rnd.randint(0, 6)))


def allowlist():
    cmd = command()
    patterns = []
    for _ in range(rnd.randint(0, 3)):
        toks = cmd.split(" ")
        k = rnd.randint(0, max(1, len(toks)))
        pat = " ".join(toks[:k]) if rnd.random() < 0.7 else command()
        if rnd.random() < 0.15:
            pat += rnd.choice(["'", '"', "\\"])
        patterns.append(pat)
    return {"op": "allowlist", "cmd": cmd, "allowlist": patterns}


for _ in range(N):
    op = rnd.choice(["toolcall"] * 3 + ["patch_split"] * 2 + ["allowlist"] * 2 + ["strip", "decode", "trunc"])
    if op == "toolcall":
        case = {"op": op, "input": toolcall()}
    elif op == "patch_split":
        case = {"op": op, "input": patch_split()}
    elif op == "allowlist":
        case = allowlist()
    elif op == "strip":
        case = {"op": op, "input": "".join(rnd.choice(WS) for _ in range(rnd.randint(0, 8)))}
    elif op == "decode":
        raw = bytes(rnd.choice(BYTES) for _ in range(rnd.randint(0, 10)))
        case = {"op": op, "b64": base64.b64encode(raw).decode()}
    else:
        case = {"op": op, "unit": rnd.choice(["a", "é", "\U0001f600", "€"]), "n": rnd.randint(7990, 8010)}
    print(json.dumps(case, ensure_ascii=True))
