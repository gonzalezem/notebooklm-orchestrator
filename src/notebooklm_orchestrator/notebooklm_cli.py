"""Subprocess wrapper for the notebooklm CLI.

All public functions log the exact command executed to log_path before running.
No function calls sys.exit(); callers handle exit codes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# NotebookLM hard source cap per notebook.
NL_MAX_SOURCES = 50

# Deliverable keyword -> (generate_type, download_type, canonical_filename)
DELIVERABLE_MAP: dict[str, tuple[str, str, str]] = {
    "briefing":     ("report",      "report",      "briefing.md"),
    "slides":       ("slide-deck",  "slide-deck",  "deck.pdf"),
    "infographic":  ("infographic", "infographic", "infographic.png"),
}

_DEFAULT_TIMEOUT = 120
_ARTIFACT_TIMEOUT = 360   # generation can be slow
_SOURCE_WAIT_TIMEOUT = 90


# ---------------------------------------------------------------------------
# Tool resolution and auth
# ---------------------------------------------------------------------------

def which_notebooklm() -> Optional[str]:
    """Resolve the notebooklm executable, preferring venv-local."""
    local = Path(sys.prefix) / "bin" / "notebooklm"
    if local.exists() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which("notebooklm")


def auth_state_path() -> Path:
    return Path.home() / ".notebooklm" / "storage_state.json"


def get_version(nb_path: str, log_path: Path) -> str:
    """Return version string from `notebooklm --version`."""
    rc, stdout, _ = _run([nb_path, "--version"], log_path, timeout=15)
    m = re.search(r"version\s+([\d.]+)", stdout, re.IGNORECASE)
    return m.group(1) if m else stdout.strip() or "unknown"


# ---------------------------------------------------------------------------
# Internal runner
# ---------------------------------------------------------------------------

def _run(
    cmd: list[str],
    log_path: Path,
    timeout: int = _DEFAULT_TIMEOUT,
    input_text: Optional[str] = None,
) -> tuple[int, str, str]:
    """
    Run a subprocess command.
    Logs 'CMD: <command>' then stdout/stderr to log_path.
    Returns (exit_code, stdout, stderr).
    """
    _append_log(log_path, f"CMD: {' '.join(cmd)}")
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )
    except subprocess.TimeoutExpired:
        msg = f"  TIMEOUT after {timeout}s"
        _append_log(log_path, msg)
        return 1, "", msg
    except Exception as exc:
        msg = f"  ERROR: {exc}"
        _append_log(log_path, msg)
        return 1, "", str(exc)

    if r.stdout.strip():
        _append_log(log_path, r.stdout.rstrip())
    if r.stderr.strip():
        _append_log(log_path, r.stderr.rstrip())
    return r.returncode, r.stdout, r.stderr


def _append_log(log_path: Path, message: str) -> None:
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(message + "\n")


# ---------------------------------------------------------------------------
# Notebook operations
# ---------------------------------------------------------------------------

def create_notebook(nb_path: str, name: str, log_path: Path) -> str:
    """Create a new notebook. Returns its ID. Raises RuntimeError on failure."""
    rc, stdout, stderr = _run([nb_path, "create", name, "--json"], log_path)
    if rc != 0:
        raise RuntimeError(f"create notebook failed (exit {rc}): {stderr.strip()}")
    try:
        data = json.loads(stdout)
        return data["notebook"]["id"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError(f"create notebook: unexpected output: {exc}") from exc


def use_notebook(nb_path: str, notebook_id: str, log_path: Path) -> None:
    """Set the active notebook context. Raises RuntimeError on failure."""
    rc, _, stderr = _run([nb_path, "use", notebook_id], log_path)
    if rc != 0:
        raise RuntimeError(f"use notebook {notebook_id} failed (exit {rc}): {stderr.strip()}")


# ---------------------------------------------------------------------------
# Source operations
# ---------------------------------------------------------------------------

def add_source(
    nb_path: str,
    url: str,
    notebook_id: str,
    log_path: Path,
) -> dict:
    """
    Add a URL source to the notebook.
    Returns {"ok": bool, "source_id": str|None, "error": str|None}.
    Never raises.
    """
    cmd = [nb_path, "source", "add", url, "--json", "-n", notebook_id]
    rc, stdout, stderr = _run(cmd, log_path)
    if rc != 0:
        return {"ok": False, "source_id": None, "error": stderr.strip() or f"exit {rc}"}
    try:
        data = json.loads(stdout)
        return {"ok": True, "source_id": data["source"]["id"], "error": None}
    except (json.JSONDecodeError, KeyError) as exc:
        return {"ok": False, "source_id": None, "error": str(exc)}


def wait_source(
    nb_path: str,
    source_id: str,
    notebook_id: str,
    log_path: Path,
    timeout: int = _SOURCE_WAIT_TIMEOUT,
) -> bool:
    """Wait for a source to finish processing. Returns True on success."""
    cmd = [nb_path, "source", "wait", source_id, "-n", notebook_id,
           "--timeout", str(timeout)]
    rc, _, _ = _run(cmd, log_path, timeout=timeout + 15)
    return rc == 0


# ---------------------------------------------------------------------------
# Chat / ask
# ---------------------------------------------------------------------------

def ask(
    nb_path: str,
    prompt_text: str,
    notebook_id: str,
    log_path: Path,
) -> str:
    """
    Ask a question. Returns the answer text.
    Raises RuntimeError on CLI failure.
    """
    cmd = [nb_path, "ask", prompt_text, "--json", "-n", notebook_id]
    rc, stdout, stderr = _run(cmd, log_path, timeout=120)
    if rc != 0:
        raise RuntimeError(f"ask failed (exit {rc}): {stderr.strip()}")
    try:
        data = json.loads(stdout)
        return data.get("answer") or stdout
    except json.JSONDecodeError:
        return stdout


# ---------------------------------------------------------------------------
# Artifact generation and download
# ---------------------------------------------------------------------------

def generate_artifact(
    nb_path: str,
    gen_type: str,
    notebook_id: str,
    log_path: Path,
) -> str:
    """
    Start artifact generation. Returns task_id.
    gen_type is the CLI keyword: "report", "slide-deck", "infographic".
    Raises RuntimeError on failure.
    """
    cmd = [nb_path, "generate", gen_type, "--json", "--no-wait", "-n", notebook_id]
    rc, stdout, stderr = _run(cmd, log_path, timeout=60)
    if rc != 0:
        raise RuntimeError(f"generate {gen_type} failed (exit {rc}): {stderr.strip()}")
    try:
        data = json.loads(stdout)
        task_id = data.get("task_id") or data.get("id")
        if not task_id:
            raise KeyError("task_id missing")
        return task_id
    except (json.JSONDecodeError, KeyError) as exc:
        raise RuntimeError(f"generate {gen_type}: unexpected output: {exc}") from exc


def wait_artifact(
    nb_path: str,
    task_id: str,
    notebook_id: str,
    log_path: Path,
    timeout: int = _ARTIFACT_TIMEOUT,
) -> bool:
    """Wait for artifact generation to complete. Returns True on success."""
    cmd = [nb_path, "artifact", "wait", task_id, "-n", notebook_id,
           "--timeout", str(timeout), "--json"]
    rc, _, _ = _run(cmd, log_path, timeout=timeout + 30)
    return rc == 0


def download_artifact(
    nb_path: str,
    dl_type: str,
    dest_path: Path,
    notebook_id: str,
    log_path: Path,
) -> bool:
    """Download the latest artifact of dl_type to dest_path. Returns True on success."""
    cmd = [nb_path, "download", dl_type, str(dest_path),
           "--force", "-n", notebook_id]
    rc, _, _ = _run(cmd, log_path, timeout=120)
    return rc == 0 and dest_path.exists()
