"""Tests for nlm-orch run: mocked notebooklm_cli and sources, no network calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import notebooklm_orchestrator.notebooklm_cli as nl_cli
from notebooklm_orchestrator.cli import cmd_run, _version_ok


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Suppress time.sleep in all tests except those that explicitly test it."""
    monkeypatch.setattr("notebooklm_orchestrator.cli.time.sleep", lambda s: None)


@pytest.fixture()
def tmp_outputs(tmp_path: Path) -> Path:
    return tmp_path / "outputs"


def _args(tmp_path: Path, **overrides) -> argparse.Namespace:
    defaults: dict[str, Any] = dict(
        query="test query",
        sources=None,
        notebook_id=None,
        prompts=None,
        deliverables=["briefing"],
        dry_run=False,
        max_results=5,
        recency="6months",
        max_duration="30m",
        min_views=1000,
        channel_allow=None,
        channel_block=None,
        run_id="test_run_id",
        outputs_dir=str(tmp_path / "outputs"),
        config=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _fake_sources_json(tmp_path: Path, n_included: int = 3) -> Path:
    """Write a minimal sources.json with n_included YouTube entries."""
    sources = [
        {
            "type": "youtube",
            "video_id": f"vid{i}",
            "url": f"https://www.youtube.com/watch?v=vid{i}",
            "title": f"Video {i}",
            "channel": "TestChannel",
            "view_count": (i + 1) * 1000,
            "duration_seconds": 300,
            "published_at": "2026-01-01",
            "included": True,
            "exclusion_reason": None,
        }
        for i in range(n_included)
    ]
    p = tmp_path / "sources.json"
    p.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

_NB_PATH = "/fake/bin/notebooklm"
_NB_ID = "nb-fake-id-0001"
_TASK_ID = "task-fake-0001"
_SRC_ID = "src-fake-0001"


def _mock_happy_nlm(mocker, deliverables=("briefing",)):
    """Patch all notebooklm_cli calls for a fully-successful run."""
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.which_notebooklm",
                 return_value=_NB_PATH)
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.auth_state_path",
                 return_value=Path("/fake/.notebooklm/storage_state.json"))
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.get_version",
                 return_value="0.3.3")
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.create_notebook",
                 return_value=_NB_ID)
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.use_notebook")
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.add_source",
                 return_value={"ok": True, "source_id": _SRC_ID, "error": None})
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.wait_source",
                 return_value=True)
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.ask",
                 return_value="Mock answer")
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.generate_artifact",
                 return_value=_TASK_ID)
    mocker.patch("notebooklm_orchestrator.notebooklm_cli.wait_artifact",
                 return_value=True)

    # download_artifact creates the file to simulate success
    def _fake_download(nb_path, dl_type, dest_path, notebook_id, log_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("mock artifact content", encoding="utf-8")
        return True

    mocker.patch("notebooklm_orchestrator.notebooklm_cli.download_artifact",
                 side_effect=_fake_download)
    # Patch auth_state_path.exists via Path mock
    mocker.patch.object(Path, "exists", return_value=True)


# ---------------------------------------------------------------------------
# 1. --dry-run exits 0, no notebooklm calls, manifest status=dry-run
# ---------------------------------------------------------------------------

def test_dry_run_exits_0_no_nlm_calls(tmp_path, monkeypatch):
    """Dry-run must not call any notebooklm operations."""
    src_file = _fake_sources_json(tmp_path)
    args = _args(tmp_path, dry_run=True, sources=str(src_file))

    called = []
    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: called.append("which") or _NB_PATH)
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: called.append("create"))
    monkeypatch.setattr(nl_cli, "add_source", lambda *a, **k: called.append("add"))

    rc = cmd_run(args)
    assert rc == 0, f"Expected exit 0, got {rc}"

    # No notebooklm subprocess calls for dry-run
    assert "create" not in called
    assert "add" not in called

    # artifacts/ directory created even for dry-run (outputs contract)
    assert (tmp_path / "outputs" / "test_run_id" / "artifacts").is_dir()

    # Manifest written with dry-run status
    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    assert manifest["status"] == "dry-run"
    assert manifest["dry_run"] is True


# ---------------------------------------------------------------------------
# 2. Missing notebooklm tool exits 4
# ---------------------------------------------------------------------------

def test_missing_notebooklm_exits_4(tmp_path, monkeypatch):
    """Exit 4 when notebooklm CLI is not found."""
    src_file = _fake_sources_json(tmp_path)
    args = _args(tmp_path, sources=str(src_file))

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: None)

    rc = cmd_run(args)
    assert rc == 4

    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failed_step"] == "preflight"


# ---------------------------------------------------------------------------
# 3. Missing auth state exits 5
# ---------------------------------------------------------------------------

def test_missing_auth_state_exits_5(tmp_path, monkeypatch):
    """Exit 5 when ~/.notebooklm/storage_state.json is absent."""
    src_file = _fake_sources_json(tmp_path)
    args = _args(tmp_path, sources=str(src_file))

    fake_auth = tmp_path / "nonexistent" / "storage_state.json"
    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path", lambda: fake_auth)
    # Do NOT create fake_auth so .exists() returns False

    rc = cmd_run(args)
    assert rc == 5

    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failed_step"] == "auth"


# ---------------------------------------------------------------------------
# 4. add_source partial failure continues: status=success with warnings
# ---------------------------------------------------------------------------

def test_add_source_partial_failure_continues(tmp_path, monkeypatch):
    """One source add fails: run continues, status=success, warning recorded."""
    src_file = _fake_sources_json(tmp_path, n_included=3)
    args = _args(tmp_path, sources=str(src_file), deliverables=["briefing"])

    call_count = {"n": 0}

    def _flaky_add(nb_path, url, notebook_id, log_path):
        call_count["n"] += 1
        if call_count["n"] == 2:
            return {"ok": False, "source_id": None, "error": "mock source error"}
        return {"ok": True, "source_id": _SRC_ID, "error": None}

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()

    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)
    monkeypatch.setattr(nl_cli, "add_source", _flaky_add)
    monkeypatch.setattr(nl_cli, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "answer")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)

    def _fake_download(nb_path, dl_type, dest, notebook_id, log_path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("content", encoding="utf-8")
        return True

    monkeypatch.setattr(nl_cli, "download_artifact", _fake_download)

    rc = cmd_run(args)
    assert rc == 0  # run completes (not a hard abort)

    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    # All deliverables succeeded => success, not partial
    assert manifest["status"] == "success"
    assert manifest["sources_add_failed"] == 1
    assert len(manifest["sources_failed_urls"]) == 1
    assert manifest["sources_add_ok"] == 2
    # Source failure recorded as warning, not as partial
    assert any(w["type"] == "source_add_failed" for w in manifest["warnings"])


# ---------------------------------------------------------------------------
# 5. Deliverable download failure -> status partial, missing_artifacts populated
# ---------------------------------------------------------------------------

def test_deliverable_download_failure_marks_partial(tmp_path, monkeypatch):
    """If artifact download fails, status=partial and missing_artifacts lists the file."""
    src_file = _fake_sources_json(tmp_path, n_included=2)
    args = _args(tmp_path, sources=str(src_file), deliverables=["briefing", "slides"])

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()

    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)
    monkeypatch.setattr(nl_cli, "add_source",
                        lambda *a, **k: {"ok": True, "source_id": _SRC_ID, "error": None})
    monkeypatch.setattr(nl_cli, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "answer")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)

    # briefing succeeds, slides fails
    def _selective_download(nb_path, dl_type, dest, notebook_id, log_path):
        if dl_type == "report":
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("briefing content", encoding="utf-8")
            return True
        return False  # slide-deck download fails

    monkeypatch.setattr(nl_cli, "download_artifact", _selective_download)

    rc = cmd_run(args)
    assert rc == 0  # still exits 0 (partial, not hard failure)

    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    assert manifest["status"] == "partial"
    assert "deck.pdf" in manifest["missing_artifacts"]
    assert "briefing.md" not in manifest["missing_artifacts"]

    downloaded = [a for a in manifest["artifacts"] if a["status"] == "downloaded"]
    assert len(downloaded) == 1
    assert downloaded[0]["keyword"] == "briefing"


# ---------------------------------------------------------------------------
# 6. --notebook-id reuse: create_notebook NOT called
# ---------------------------------------------------------------------------

def test_notebook_id_reuse_skips_create(tmp_path, monkeypatch):
    """When --notebook-id is given, create_notebook must not be called."""
    src_file = _fake_sources_json(tmp_path, n_included=1)
    args = _args(tmp_path, sources=str(src_file), notebook_id="existing-nb-id",
                 deliverables=["briefing"])

    create_called = []
    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()

    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook",
                        lambda *a, **k: create_called.append(True) or _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)
    monkeypatch.setattr(nl_cli, "add_source",
                        lambda *a, **k: {"ok": True, "source_id": _SRC_ID, "error": None})
    monkeypatch.setattr(nl_cli, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "answer")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)

    def _fake_download(nb_path, dl_type, dest, notebook_id, log_path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("content", encoding="utf-8")
        return True

    monkeypatch.setattr(nl_cli, "download_artifact", _fake_download)

    rc = cmd_run(args)
    assert rc == 0
    assert not create_called, "create_notebook must not be called when --notebook-id given"

    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    assert manifest["notebook_id"] == "existing-nb-id"


# ---------------------------------------------------------------------------
# 7. zero included sources from --sources -> exits 3
# ---------------------------------------------------------------------------

def test_zero_included_sources_exits_3(tmp_path, monkeypatch):
    """If sources.json has no included entries, exit 3 without calling NLM."""
    # Write sources.json with all excluded
    sources = [{"url": "https://yt.com/watch?v=x", "included": False,
                "exclusion_reason": "recency"}]
    p = tmp_path / "sources.json"
    p.write_text(json.dumps({"sources": sources}), encoding="utf-8")

    args = _args(tmp_path, sources=str(p))

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()
    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")

    create_called = []
    monkeypatch.setattr(nl_cli, "create_notebook",
                        lambda *a, **k: create_called.append(True) or _NB_ID)

    rc = cmd_run(args)
    assert rc == 3
    assert not create_called

    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    assert manifest["status"] == "partial"
    assert manifest["failed_step"] == "sources"


# ---------------------------------------------------------------------------
# 8. Happy-path: status=success, all artifacts downloaded
# ---------------------------------------------------------------------------

def test_happy_path_success(tmp_path, monkeypatch):
    """Full happy path: success status, all artifacts downloaded."""
    src_file = _fake_sources_json(tmp_path, n_included=3)
    args = _args(tmp_path, sources=str(src_file),
                 deliverables=["briefing", "slides", "infographic"])

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()

    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)
    monkeypatch.setattr(nl_cli, "add_source",
                        lambda *a, **k: {"ok": True, "source_id": _SRC_ID, "error": None})
    monkeypatch.setattr(nl_cli, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "Mock answer text")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)

    def _fake_download(nb_path, dl_type, dest, notebook_id, log_path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f"content for {dl_type}", encoding="utf-8")
        return True

    monkeypatch.setattr(nl_cli, "download_artifact", _fake_download)

    rc = cmd_run(args)
    assert rc == 0

    run_dir = tmp_path / "outputs" / "test_run_id"
    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["status"] == "success"
    assert manifest["notebook_id"] == _NB_ID
    assert manifest["sources_add_ok"] == 3
    assert manifest["sources_add_failed"] == 0
    assert manifest["missing_artifacts"] == []
    assert len(manifest["artifacts"]) == 3
    assert all(a["status"] == "downloaded" for a in manifest["artifacts"])

    # Artifact files exist on disk
    assert (run_dir / "artifacts" / "briefing.md").exists()
    assert (run_dir / "artifacts" / "deck.pdf").exists()
    assert (run_dir / "artifacts" / "infographic.png").exists()

    # notes/ dir created and ask_0.md written
    assert (run_dir / "notes").is_dir()
    assert (run_dir / "notes" / "ask_0.md").exists()

    # source_add_delay_seconds recorded in manifest
    assert manifest["source_add_delay_seconds"] == 2


# ---------------------------------------------------------------------------
# 9. _version_ok unit tests
# ---------------------------------------------------------------------------

def test_version_ok_equal():
    assert _version_ok("0.3.3", "0.3.3") is True

def test_version_ok_greater():
    assert _version_ok("0.4.0", "0.3.3") is True

def test_version_ok_below():
    assert _version_ok("0.3.2", "0.3.3") is False

def test_version_ok_unparseable_passes():
    assert _version_ok("unknown", "0.3.3") is True

def test_version_ok_empty_passes():
    assert _version_ok("", "0.3.3") is True


# ---------------------------------------------------------------------------
# 10. Version gate: version < 0.3.3 exits 4 with status=failed
# ---------------------------------------------------------------------------

def test_version_gate_exits_4(tmp_path, monkeypatch):
    """If notebooklm version < 0.3.3, exit 4 and write failed manifest."""
    src_file = _fake_sources_json(tmp_path)
    args = _args(tmp_path, sources=str(src_file))

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()
    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.2")

    rc = cmd_run(args)
    assert rc == 4

    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failed_step"] == "preflight"
    assert "0.3.2" in manifest["error_summary"]


# ---------------------------------------------------------------------------
# 11. Rate limiting: time.sleep called between source adds
# ---------------------------------------------------------------------------

def test_rate_limit_delay_called_between_adds(tmp_path, monkeypatch):
    """time.sleep(2) must be called between source adds (N-1 times for N sources)."""
    src_file = _fake_sources_json(tmp_path, n_included=3)
    args = _args(tmp_path, sources=str(src_file), deliverables=["briefing"])

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()
    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)
    monkeypatch.setattr(nl_cli, "add_source",
                        lambda *a, **k: {"ok": True, "source_id": _SRC_ID, "error": None})
    monkeypatch.setattr(nl_cli, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "answer")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)

    def _fake_download(nb_path, dl_type, dest, notebook_id, log_path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("content", encoding="utf-8")
        return True

    monkeypatch.setattr(nl_cli, "download_artifact", _fake_download)

    sleep_calls = []
    monkeypatch.setattr("notebooklm_orchestrator.cli.time.sleep",
                        lambda s: sleep_calls.append(s))

    rc = cmd_run(args)
    assert rc == 0
    # 3 sources -> 2 sleeps (not after the last one)
    assert sleep_calls == [2, 2]


# ---------------------------------------------------------------------------
# 12. source_add_no_id: ok=True but source_id=None -> warning, count as succeeded
# ---------------------------------------------------------------------------

def test_source_add_no_id_warning(tmp_path, monkeypatch):
    """add_source ok=True but source_id=None: count as add_ok, emit source_add_no_id warning."""
    src_file = _fake_sources_json(tmp_path, n_included=2)
    args = _args(tmp_path, sources=str(src_file), deliverables=["briefing"])

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()
    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)

    call_count = {"n": 0}
    def _no_id_add(nb_path, url, notebook_id, log_path):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"ok": True, "source_id": None, "error": None}  # no id
        return {"ok": True, "source_id": _SRC_ID, "error": None}

    wait_called = []
    monkeypatch.setattr(nl_cli, "add_source", _no_id_add)
    monkeypatch.setattr(nl_cli, "wait_source",
                        lambda *a, **k: wait_called.append(True) or True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "answer")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)
    monkeypatch.setattr("notebooklm_orchestrator.cli.time.sleep", lambda s: None)

    def _fake_download(nb_path, dl_type, dest, notebook_id, log_path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("content", encoding="utf-8")
        return True

    monkeypatch.setattr(nl_cli, "download_artifact", _fake_download)

    rc = cmd_run(args)
    assert rc == 0

    manifest = json.loads((tmp_path / "outputs" / "test_run_id" / "run_manifest.json").read_text())
    assert manifest["sources_add_ok"] == 2  # both counted as succeeded
    assert manifest["status"] == "success"
    # warning emitted for the no-id case
    assert any(w["type"] == "source_add_no_id" for w in manifest["warnings"])
    # wait_source called only once (for the source that had an id)
    assert len(wait_called) == 1


# ---------------------------------------------------------------------------
# 13. notes/ created and ask_0.md written
# ---------------------------------------------------------------------------

def test_notes_dir_and_ask_file_written(tmp_path, monkeypatch):
    """notes/ dir exists and ask_0.md is written with the prompt response."""
    src_file = _fake_sources_json(tmp_path, n_included=1)
    args = _args(tmp_path, sources=str(src_file), deliverables=["briefing"])

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path",
                        lambda: tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").touch()
    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)
    monkeypatch.setattr(nl_cli, "add_source",
                        lambda *a, **k: {"ok": True, "source_id": _SRC_ID, "error": None})
    monkeypatch.setattr(nl_cli, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "The answer text")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)
    monkeypatch.setattr("notebooklm_orchestrator.cli.time.sleep", lambda s: None)

    def _fake_download(nb_path, dl_type, dest, notebook_id, log_path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("content", encoding="utf-8")
        return True

    monkeypatch.setattr(nl_cli, "download_artifact", _fake_download)

    rc = cmd_run(args)
    assert rc == 0

    run_dir = tmp_path / "outputs" / "test_run_id"
    assert (run_dir / "notes").is_dir()
    ask_file = run_dir / "notes" / "ask_0.md"
    assert ask_file.exists()
    assert ask_file.read_text() == "The answer text"

    manifest = json.loads((run_dir / "run_manifest.json").read_text())
    assert manifest["prompts_used"][0]["response_file"] == str(ask_file)
