"""Tests for _write_handoff and the handoff trigger in cmd_run. No network."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
import pytest

import notebooklm_orchestrator.notebooklm_cli as nl_cli
from notebooklm_orchestrator.cli import _write_handoff, cmd_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("notebooklm_orchestrator.cli.time.sleep", lambda s: None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RUN_ID = "test_handoff_run"
_QUERY = "test query about AI workflows"


def _artifacts(*specs) -> list[dict]:
    """Build artifact dicts. Each spec is (keyword, status)."""
    _filenames = {"slides": "deck.pdf", "infographic": "infographic.png", "briefing": "briefing.md"}
    result = []
    for keyword, status in specs:
        filename = _filenames.get(keyword, keyword)
        entry: dict = {"keyword": keyword, "filename": filename, "status": status}
        if status == "downloaded":
            entry["path"] = f"/fake/outputs/{_RUN_ID}/artifacts/{filename}"
        result.append(entry)
    return result


def _call_write_handoff(
    tmp_path: Path,
    deliverables: list[str],
    artifact_specs: list[tuple[str, str]],
) -> Path:
    """Call _write_handoff and return the handoff file path."""
    run_dir = tmp_path / "outputs" / _RUN_ID
    run_dir.mkdir(parents=True)
    handoff_path = run_dir / "deliverables_handoff.md"
    arts = _artifacts(*artifact_specs)
    _write_handoff(handoff_path, deliverables, arts, _QUERY, _RUN_ID, run_dir)
    return handoff_path


def _fake_sources_json(tmp_path: Path) -> Path:
    sources = [
        {
            "type": "youtube",
            "video_id": "vid0",
            "url": "https://www.youtube.com/watch?v=vid0",
            "title": "Video 0",
            "channel": "TestChannel",
            "view_count": 5000,
            "duration_seconds": 300,
            "published_at": "2026-01-01",
            "included": True,
            "exclusion_reason": None,
        }
    ]
    p = tmp_path / "sources.json"
    p.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return p


_NB_PATH = "/fake/bin/notebooklm"
_NB_ID = "nb-fake-0001"
_TASK_ID = "task-fake-0001"
_SRC_ID = "src-fake-0001"


def _run_args(tmp_path: Path, prompt_file: Path, **overrides) -> argparse.Namespace:
    sources_path = _fake_sources_json(tmp_path)
    defaults: dict[str, Any] = dict(
        query="test query",
        sources=str(sources_path),
        notebook_id=None,
        prompts=[str(prompt_file)],
        deliverables=["slides", "infographic", "briefing"],
        intent="strategy",
        dry_run=False,
        review=False,
        max_results=5,
        recency="6months",
        max_duration="30m",
        min_views=1000,
        channel_allow=None,
        channel_block=None,
        run_id="handoff_run",
        outputs_dir=str(tmp_path / "outputs"),
        config=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _patch_nlm(monkeypatch, tmp_path: Path, download_fn):
    """Patch all NLM module functions for a full run."""
    auth_file = tmp_path / "storage_state.json"
    auth_file.write_text("{}")

    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path", lambda: auth_file)
    monkeypatch.setattr(nl_cli, "get_version", lambda *a, **k: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)
    monkeypatch.setattr(nl_cli, "add_source",
                        lambda *a, **k: {"ok": True, "source_id": _SRC_ID, "error": None})
    monkeypatch.setattr(nl_cli, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "Mock answer")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "download_artifact", download_fn)


# ---------------------------------------------------------------------------
# 1. File written when slides downloaded
# ---------------------------------------------------------------------------

def test_handoff_written_slides_downloaded(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides"],
        artifact_specs=[("slides", "downloaded")],
    )
    assert handoff.exists()


# ---------------------------------------------------------------------------
# 2. File written when infographic downloaded
# ---------------------------------------------------------------------------

def test_handoff_written_infographic_downloaded(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["infographic"],
        artifact_specs=[("infographic", "downloaded")],
    )
    assert handoff.exists()


# ---------------------------------------------------------------------------
# 3. File written when both downloaded
# ---------------------------------------------------------------------------

def test_handoff_written_both_downloaded(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides", "infographic"],
        artifact_specs=[("slides", "downloaded"), ("infographic", "downloaded")],
    )
    assert handoff.exists()
    text = handoff.read_text()
    assert "### Slide deck (deck.pdf)" in text
    assert "### Infographic (infographic.png)" in text


# ---------------------------------------------------------------------------
# 4. File NOT written when both visual downloads failed
# ---------------------------------------------------------------------------

def test_handoff_not_written_all_failed(tmp_path, monkeypatch):
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("test prompt")

    def _all_fail(nb_path, dl_type, dest_path, notebook_id, log_path):
        return False

    _patch_nlm(monkeypatch, tmp_path, _all_fail)
    args = _run_args(tmp_path, prompt_file, deliverables=["slides", "infographic", "briefing"])
    cmd_run(args)
    handoff = tmp_path / "outputs" / "handoff_run" / "deliverables_handoff.md"
    assert not handoff.exists()


# ---------------------------------------------------------------------------
# 5. Intro paragraph present before Section 1
# ---------------------------------------------------------------------------

def test_handoff_intro_paragraph_present(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides"],
        artifact_specs=[("slides", "downloaded")],
    )
    text = handoff.read_text()
    intro_idx = text.find("Your deliverables are ready.")
    section1_idx = text.find("## Generated deliverables")
    assert intro_idx != -1
    assert section1_idx != -1
    assert intro_idx < section1_idx


# ---------------------------------------------------------------------------
# 6. No Markdown hyperlinks in generated file
# ---------------------------------------------------------------------------

def test_handoff_no_markdown_hyperlinks(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides", "infographic"],
        artifact_specs=[("slides", "downloaded"), ("infographic", "downloaded")],
    )
    text = handoff.read_text()
    assert "](http" not in text
    assert "(http" not in text


# ---------------------------------------------------------------------------
# 7. Manifest handoff_path set when file is written
# ---------------------------------------------------------------------------

def test_handoff_manifest_handoff_path_set(tmp_path, monkeypatch):
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("test prompt")

    def _succeed(nb_path, dl_type, dest_path, notebook_id, log_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("mock content", encoding="utf-8")
        return True

    _patch_nlm(monkeypatch, tmp_path, _succeed)
    args = _run_args(tmp_path, prompt_file, deliverables=["slides", "infographic", "briefing"])
    cmd_run(args)
    manifest_path = tmp_path / "outputs" / "handoff_run" / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["handoff_path"] is not None
    assert "deliverables_handoff.md" in manifest["handoff_path"]


# ---------------------------------------------------------------------------
# 8. Manifest handoff_path null for briefing-only run
# ---------------------------------------------------------------------------

def test_handoff_manifest_handoff_path_null_briefing(tmp_path, monkeypatch):
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("test prompt")

    def _succeed(nb_path, dl_type, dest_path, notebook_id, log_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text("mock content", encoding="utf-8")
        return True

    _patch_nlm(monkeypatch, tmp_path, _succeed)
    args = _run_args(tmp_path, prompt_file, deliverables=["briefing"])
    cmd_run(args)
    manifest_path = tmp_path / "outputs" / "handoff_run" / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["handoff_path"] is None


# ---------------------------------------------------------------------------
# 9. Google Slides section present when deck downloaded
# ---------------------------------------------------------------------------

def test_handoff_google_slides_section_present(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides"],
        artifact_specs=[("slides", "downloaded")],
    )
    text = handoff.read_text()
    assert "## Make editable in Google Slides" in text


# ---------------------------------------------------------------------------
# 10. slides-only: deck subsection present, infographic PNG subsection absent
# ---------------------------------------------------------------------------

def test_handoff_slides_only_deck_subsection(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides"],
        artifact_specs=[("slides", "downloaded")],
    )
    text = handoff.read_text()
    # Deck subsection present in Google Slides
    assert "### Slide deck (deck.pdf)" in text
    # Infographic PNG subsection absent
    assert "Upload `artifacts/infographic.png`" not in text


# ---------------------------------------------------------------------------
# 11. infographic-only: PNG subsection present, deck subsection absent
# ---------------------------------------------------------------------------

def test_handoff_infographic_only_png_subsection(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["infographic"],
        artifact_specs=[("infographic", "downloaded")],
    )
    text = handoff.read_text()
    # PNG subsection present
    assert "### Infographic (infographic.png)" in text
    # Deck subsection absent
    assert "Upload `artifacts/deck.pdf`" not in text


# ---------------------------------------------------------------------------
# 12. Partial run: slides failed, infographic downloaded -> file written, deck listed as not downloaded
# ---------------------------------------------------------------------------

def test_handoff_partial_run_infographic_only_downloaded(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides", "infographic"],
        artifact_specs=[
            ("slides", "download_failed"),
            ("infographic", "downloaded"),
        ],
    )
    assert handoff.exists()
    text = handoff.read_text()
    # Slides listed as not downloaded in Section 1
    assert "**slides** - `-` (not downloaded)" in text
    # Infographic listed as downloaded
    assert "**infographic**" in text
    assert "(downloaded)" in text
    # Only infographic subsections in Canva/Google Slides
    assert "### Infographic (infographic.png)" in text
    assert "Upload `artifacts/deck.pdf`" not in text


# ---------------------------------------------------------------------------
# 13. Section 1 shows all requested deliverables
# ---------------------------------------------------------------------------

def test_handoff_section1_shows_all_requested(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides", "infographic", "briefing"],
        artifact_specs=[
            ("slides", "downloaded"),
            ("infographic", "downloaded"),
            ("briefing", "downloaded"),
        ],
    )
    text = handoff.read_text()
    assert "**slides**" in text
    assert "**infographic**" in text
    assert "**briefing**" in text


# ---------------------------------------------------------------------------
# 14. Checklist always present when file written
# ---------------------------------------------------------------------------

def test_handoff_checklist_present(tmp_path):
    handoff = _call_write_handoff(
        tmp_path,
        deliverables=["slides"],
        artifact_specs=[("slides", "downloaded")],
    )
    text = handoff.read_text()
    assert "## Post-editing checklist" in text
    assert "- [ ] Apply brand colors" in text
