"""Export an explicit, credential-free source allowlist at a fixed Git ref."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

root = Path(__file__).resolve().parents[3]
ref = "105061c4674a4e0666c4515c99476abe214a145a"
output = Path(sys.argv[1]).resolve()
output.mkdir(parents=True, exist_ok=False)
names = subprocess.check_output(
    ["git", "ls-tree", "-r", "--name-only", ref, "nakedagent", "tests", "LICENSE"], cwd=root
).decode().splitlines()
files = {name: subprocess.check_output(["git", "show", f"{ref}:{name}"], cwd=root)
         for name in names if name.endswith(".py") or name == "LICENSE"}
for name in ("smoke.py", "guest_probe.py"):
    relative = "docs/risk-contract/docker-sandbox/" + name
    files[relative] = (root / relative).read_bytes()
manifest = {"source_ref": ref, "files": {
    name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
files["manifest.json"] = (output / "manifest.json").read_bytes()
with tarfile.open(output / "source.tar", "w") as archive:
    for name, content in sorted(files.items()):
        info = tarfile.TarInfo(name)
        info.size = len(content)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(content))
print(json.dumps({"files": len(manifest["files"]), "archive": str(output / "source.tar"),
                  "sha256": hashlib.sha256((output / "source.tar").read_bytes()).hexdigest()}))
