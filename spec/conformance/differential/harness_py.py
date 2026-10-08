"""Reference side of the differential test: run cases.jsonl through the Python implementation.

    python3 harness_py.py REPO_ROOT cases.jsonl > out_py.jsonl

Run it on Linux: the allowlist op uses the POSIX word splitter, which the reference only selects on POSIX.
"""

import base64
import json
import sys

sys.path.insert(0, sys.argv[1])
from nakedagent import tools  # noqa: E402
from nakedagent.toolcall import parse  # noqa: E402

for line in open(sys.argv[2], encoding="utf-8"):
    case = json.loads(line)
    op = case["op"]
    if op == "toolcall":
        result = [[c.tool, c.args, c.content] for c in parse(case["input"])]
    elif op == "patch_split":
        try:
            result = list(tools._split_search_replace(case["input"]))
        except ValueError as e:
            result = {"error": str(e)}
    elif op == "allowlist":
        result = tools._is_allowed_shell_command(case["cmd"], tuple(case["allowlist"]))
    elif op == "strip":
        result = case["input"].strip()
    elif op == "decode":
        result = base64.b64decode(case["b64"]).decode("utf-8", "replace")
    elif op == "trunc":
        result = tools._truncate(case["unit"] * case["n"])
    else:
        raise SystemExit(f"unknown op {op!r}")
    print(json.dumps(result, ensure_ascii=True))
