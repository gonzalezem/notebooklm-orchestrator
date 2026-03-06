"""Live end-to-end smoke test. Requires real NotebookLM auth and network.

Run with: pytest -m live

Never executed in CI (excluded by -m "not live").
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _notebooklm_path() -> str | None:
    local = Path(sys.prefix) / "bin" / "notebooklm"
    if local.exists():
        return str(local)
    return shutil.which("notebooklm")


def _auth_ok() -> bool:
    return (Path.home() / ".notebooklm" / "storage_state.json").exists()


def _version_ok(path: str) -> bool:
    try:
        out = subprocess.check_output([path, "--version"], text=True, timeout=15)
        import re
        m = re.search(r"([\d]+)\.([\d]+)\.([\d]+)", out)
        if not m:
            return True  # unparseable: don't block
        v = tuple(int(x) for x in m.groups())
        return v >= (0, 3, 3)
    except Exception:
        return False


@pytest.mark.live
def test_run_briefing_smoke(tmp_path):
    """End-to-end: curate sources, create notebook, generate briefing, download."""
    nb = _notebooklm_path()
    if nb is None:
        pytest.skip("notebooklm CLI not found")
    if not _auth_ok():
        pytest.skip("~/.notebooklm/storage_state.json not present; run nlm-orch login first")
    if not _version_ok(nb):
        pytest.skip("notebooklm CLI version < 0.3.3")

    result = subprocess.run(
        [
            sys.executable, "-m", "notebooklm_orchestrator.cli",
            "run", "claude code skills",
            "--deliverables", "briefing",
            "--outputs-dir", str(tmp_path / "outputs"),
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )

    assert result.returncode == 0, f"nlm-orch run exited {result.returncode}:\n{result.stderr}"

    # Locate the run dir (single subdir created)
    outputs_root = tmp_path / "outputs"
    run_dirs = [d for d in outputs_root.iterdir() if d.is_dir()]
    assert len(run_dirs) == 1, f"Expected 1 run dir, found: {run_dirs}"
    run_dir = run_dirs[0]

    assert (run_dir / "artifacts" / "briefing.md").exists(), "briefing.md not downloaded"
    assert (run_dir / "notes" / "ask_0.md").exists(), "ask_0.md not written"
    assert (run_dir / "run_manifest.json").exists(), "run_manifest.json missing"

    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] in {"success", "partial"}, (
        f"Unexpected status: {manifest['status']!r}; "
        f"failed_step={manifest.get('failed_step')}"
    )
    # Partial is tolerable only if there is no failed_step (i.e., source warnings only)
    if manifest["status"] == "partial":
        assert manifest.get("failed_step") is None, (
            f"Run ended partial with failed_step={manifest['failed_step']!r}"
        )
