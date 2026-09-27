# Publishing Runbook — nakedagent

This runbook documents the exact procedure to publish **nakedagent** to **PyPI** and **GitHub Releases** following the HUMMBL gold standard.

---

## 1. Package Status & Pre-Flight Checks

Before releasing:
1. **Zero Runtime Dependencies**: The package specifies `dependencies = []` in `pyproject.toml`. Confirmed:
   ```bash
   python -c "import tomllib; deps = tomllib.load(open('pyproject.toml','rb'))['project'].get('dependencies', []); assert len(deps) == 0"
   ```
2. **Test Suite**: 100% green test pass across unit tests:
   ```bash
   python -m unittest discover -s tests -v
   ```
3. **Clean Build**: Distribution packages (`.tar.gz` and `.whl`) build with zero warnings:
   ```bash
   python -m build
   ```

---

## 2. Recommended Release Path: PyPI Trusted Publishing (OIDC)

PyPI Trusted Publishing eliminates long-lived API tokens in favor of short-lived OIDC exchange tokens between GitHub Actions and PyPI.

### Step 1: Register the Trusted Publisher on PyPI
1. Log into [pypi.org](https://pypi.org).
2. Go to **Account Settings → Publishing** ([https://pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/)).
3. Under **Add a publisher**, select **GitHub**:
   - **PyPI Project Name**: `nakedagent`
   - **Owner**: `hummbl-io`
   - **Repository name**: `nakedagent`
   - **Workflow name**: `publish-pypi.yml`
   - **Environment name**: `pypi`
4. Click **Add**.

### Step 2: Tag and Release
Once merged to `main`:
```bash
git checkout main
git pull origin main
git tag -s v0.1.0 -m "Release v0.1.0: Zero-dependency coding agent foundation"
git push origin v0.1.0
```

### Step 3: Automated Workflow Execution
The `.github/workflows/publish-pypi.yml` workflow will automatically:
1. Verify the tag matches `pyproject.toml` version `0.1.0`.
2. Run the full unit test suite.
3. Build the source distribution (`sdist`) and wheel (`bdist_wheel`).
4. Validate zero runtime dependencies.
5. Publish directly to PyPI via OIDC.
6. Generate SHA-256 checksums.
7. Create a GitHub Release attaching the wheel, sdist, and checksums.

---

## 3. Alternative Direct Manual Upload (First-time bootstrap)

If you prefer to claim the `nakedagent` name immediately on PyPI via token:
```bash
# Build distributions
python -m build

# Upload to PyPI using twine
pip install twine
python -m twine upload dist/*
```
*(When prompted, enter `__token__` as username and your PyPI API token as password).*

---

## 4. Post-Publish Verification

Verify in a clean environment:
```bash
# Test installation from PyPI
pip install nakedagent

# Verify CLI entry point
nakedagent --help

# Verify module execution
python -m nakedagent --help
```
