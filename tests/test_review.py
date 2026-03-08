"""Tests for --review (curation review mode). No network, no NLM calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

import notebooklm_orchestrator.notebooklm_cli as nl_cli
from notebooklm_orchestrator.cli import cmd_run


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("notebooklm_orchestrator.cli.time.sleep", lambda s: None)


def _review_args(tmp_path: Path, sources_path: Path, **overrides) -> argparse.Namespace:
    defaults: dict[str, Any] = dict(
        query="test query",
        sources=str(sources_path),
        review=True,
        dry_run=False,
        notebook_id=None,
        prompts=None,
        deliverables=["briefing"],
        intent="strategy",
        max_results=5,
        recency="6months",
        max_duration="30m",
        min_views=1000,
        channel_allow=None,
        channel_block=None,
        run_id="review_run",
        outputs_dir=str(tmp_path / "outputs"),
        config=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _make_sources(
    tmp_path: Path,
    included: int = 3,
    excluded_reasons: list[str] | None = None,
) -> Path:
    """Write sources.json with `included` passing sources and one entry per excluded reason."""
    if excluded_reasons is None:
        excluded_reasons = ["recency", "min_views", "cap"]
    sources = []
    for i in range(included):
        sources.append({
            "type": "youtube",
            "video_id": f"v{i}",
            "url": f"https://www.youtube.com/watch?v=v{i}",
            "title": f"Included Video {i}",
            "channel": "TestChan",
            "view_count": 5000,
            "duration_seconds": 300 + i * 60,  # 5m00s, 6m00s, 7m00s ...
            "published_at": "2026-01-15",
            "included": True,
            "exclusion_reason": None,
        })
    for j, reason in enumerate(excluded_reasons):
        sources.append({
            "type": "youtube",
            "video_id": f"ex{j}",
            "url": f"https://www.youtube.com/watch?v=ex{j}",
            "title": f"Excluded Video {j}",
            "channel": "TestChan",
            "view_count": 100,
            "duration_seconds": 600,
            "published_at": "2020-01-01",
            "included": False,
            "exclusion_reason": reason,
        })
    p = tmp_path / "sources.json"
    p.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return p


def _run_dir(tmp_path: Path) -> Path:
    return tmp_path / "outputs" / "review_run"


def _report_path(tmp_path: Path) -> Path:
    return _run_dir(tmp_path) / "curation_report.md"


def _manifest(tmp_path: Path) -> dict:
    return json.loads((_run_dir(tmp_path) / "run_manifest.json").read_text())


# ---------------------------------------------------------------------------
# 1. Exit code 0
# ---------------------------------------------------------------------------

def test_review_exits_0(tmp_path):
    src = _make_sources(tmp_path)
    rc = cmd_run(_review_args(tmp_path, src))
    assert rc == 0


# ---------------------------------------------------------------------------
# 2. Report file written
# ---------------------------------------------------------------------------

def test_review_writes_report(tmp_path):
    src = _make_sources(tmp_path)
    cmd_run(_review_args(tmp_path, src))
    assert _report_path(tmp_path).exists()


# ---------------------------------------------------------------------------
# 3. Manifest status and review_report_path
# ---------------------------------------------------------------------------

def test_review_manifest_status(tmp_path):
    src = _make_sources(tmp_path)
    cmd_run(_review_args(tmp_path, src))
    m = _manifest(tmp_path)
    assert m["status"] == "review"
    assert "review_report_path" in m
    assert "curation_report.md" in m["review_report_path"]


# ---------------------------------------------------------------------------
# 4. No NLM calls
# ---------------------------------------------------------------------------

def test_review_no_nlm_calls(tmp_path, monkeypatch):
    src = _make_sources(tmp_path)
    called = []
    monkeypatch.setattr(nl_cli, "create_notebook",
                        lambda *a, **k: called.append("create") or "nb-id")
    cmd_run(_review_args(tmp_path, src))
    assert called == []


# ---------------------------------------------------------------------------
# 5. Included table row count matches sources
# ---------------------------------------------------------------------------

def test_review_included_table_rows(tmp_path):
    src = _make_sources(tmp_path, included=4)
    cmd_run(_review_args(tmp_path, src))
    report = _report_path(tmp_path).read_text()
    # Data rows: start with "| ", not the header "| #", not the separator "|---"
    # Included table rows have 9 pipe chars (8 columns)
    data_rows = [
        line for line in report.splitlines()
        if line.startswith("| ")
        and not line.startswith("| #")
        and not line.startswith("|---")
        and line.count("|") >= 9
    ]
    assert len(data_rows) == 4


# ---------------------------------------------------------------------------
# 6. Excluded summary counts (cap as its own row)
# ---------------------------------------------------------------------------

def test_review_excluded_summary_counts(tmp_path):
    reasons = ["recency", "min_views", "cap", "cap"]  # 2 cap entries
    src = _make_sources(tmp_path, included=2, excluded_reasons=reasons)
    cmd_run(_review_args(tmp_path, src))
    report = _report_path(tmp_path).read_text()
    assert "## Excluded sources (4)" in report
    assert "| cap | 2 |" in report
    assert "| recency | 1 |" in report
    assert "| min_views | 1 |" in report


# ---------------------------------------------------------------------------
# 7. Section 3 heading present
# ---------------------------------------------------------------------------

def test_review_section3_present(tmp_path):
    src = _make_sources(tmp_path)
    cmd_run(_review_args(tmp_path, src))
    report = _report_path(tmp_path).read_text()
    assert "## How to edit sources.json and rerun" in report


# ---------------------------------------------------------------------------
# 8. Duration formatted as Xm Ys
# ---------------------------------------------------------------------------

def test_review_duration_format(tmp_path):
    # included=1 -> duration_seconds=300 -> 5m 00s
    src = _make_sources(tmp_path, included=1, excluded_reasons=[])
    cmd_run(_review_args(tmp_path, src))
    report = _report_path(tmp_path).read_text()
    assert "5m 00s" in report


# ---------------------------------------------------------------------------
# 9. Notes column present and empty in all data rows
# ---------------------------------------------------------------------------

def test_review_notes_column(tmp_path):
    src = _make_sources(tmp_path, included=2, excluded_reasons=[])
    cmd_run(_review_args(tmp_path, src))
    report = _report_path(tmp_path).read_text()
    assert "| Notes |" in report
    data_rows = [
        line for line in report.splitlines()
        if line.startswith("| ")
        and not line.startswith("| #")
        and not line.startswith("|---")
        and line.count("|") >= 9
    ]
    assert len(data_rows) == 2
    assert all(row.endswith("|  |") for row in data_rows)


# ---------------------------------------------------------------------------
# 10. artifacts/ and notes/ dirs exist and are empty
# ---------------------------------------------------------------------------

def test_review_artifacts_and_notes_dirs_exist(tmp_path):
    src = _make_sources(tmp_path)
    cmd_run(_review_args(tmp_path, src))
    run_dir = _run_dir(tmp_path)
    assert (run_dir / "artifacts").is_dir()
    assert (run_dir / "notes").is_dir()
    assert list((run_dir / "artifacts").iterdir()) == []
    assert list((run_dir / "notes").iterdir()) == []


# ---------------------------------------------------------------------------
# 11. DONE line on stdout
# ---------------------------------------------------------------------------

def test_review_done_line(tmp_path, capsys):
    # 3 included, 1 excluded -> total 4
    src = _make_sources(tmp_path, included=3, excluded_reasons=["recency"])
    cmd_run(_review_args(tmp_path, src))
    out = capsys.readouterr().out
    assert "status=review" in out
    assert "sources=3/4" in out
    assert "report=curation_report.md" in out


# ---------------------------------------------------------------------------
# 12. --review + --dry-run: review wins
# ---------------------------------------------------------------------------

def test_review_plus_dry_run_review_wins(tmp_path):
    src = _make_sources(tmp_path)
    args = _review_args(tmp_path, src, dry_run=True)
    rc = cmd_run(args)
    assert rc == 0
    assert _report_path(tmp_path).exists()
    assert _manifest(tmp_path)["status"] == "review"


# ---------------------------------------------------------------------------
# 13. --sources + --review: no yt-dlp, report from provided file
# ---------------------------------------------------------------------------

def test_review_with_sources_flag(tmp_path):
    prior = tmp_path / "prior_sources.json"
    prior.write_text(json.dumps({"sources": [{
        "type": "youtube", "video_id": "abc",
        "url": "https://www.youtube.com/watch?v=abc",
        "title": "A Prior Video", "channel": "PriorChan",
        "view_count": 9999, "duration_seconds": 120,
        "published_at": "2026-02-01",
        "included": True, "exclusion_reason": None,
    }]}), encoding="utf-8")
    args = _review_args(tmp_path, prior)
    rc = cmd_run(args)
    assert rc == 0
    report = _report_path(tmp_path).read_text()
    assert "A Prior Video" in report
    assert "## How to edit sources.json and rerun" in report


# ---------------------------------------------------------------------------
# 14. Zero included sources -> exit 3, no report written
# ---------------------------------------------------------------------------

def test_review_zero_sources_exits_3(tmp_path):
    src = _make_sources(tmp_path, included=0, excluded_reasons=["min_views", "recency"])
    args = _review_args(tmp_path, src)
    rc = cmd_run(args)
    assert rc == 3
    assert not _report_path(tmp_path).exists()
