"""Unit tests for quality scoring (score_source) and cap sorting. No network."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from notebooklm_orchestrator.sources import apply_filters, score_source

# Fixed reference date for all recency calculations
TODAY = date(2026, 3, 7)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _src(
    view_count=None,
    published_at=None,
    duration_seconds=None,
    video_id="v1",
    **extra,
) -> dict:
    """Build a minimal normalized source dict."""
    return {
        "type": "youtube",
        "video_id": video_id,
        "title": "Test Video",
        "channel": "TestChan",
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "view_count": view_count,
        "duration_seconds": duration_seconds,
        "published_at": published_at,
        "included": True,
        "exclusion_reason": None,
        **extra,
    }


def _filter1(entries, cap=1):
    """Run apply_filters with permissive settings and a given cap."""
    return apply_filters(
        entries,
        channel_allow=None,
        channel_block=None,
        recency="all",
        max_duration="all",
        min_views=0,
        selection_cap=cap,
    )


# ---------------------------------------------------------------------------
# 1. High views + very recent + ideal duration = 100
# ---------------------------------------------------------------------------

def test_score_high_views_recent_ideal():
    # 100k views + 6 days old + 15 min → 40 + 40 + 20 = 100
    pub = str(TODAY - timedelta(days=6))
    src = _src(view_count=100_000, published_at=pub, duration_seconds=900)
    score, factors = score_source(src, today=TODAY)
    assert score == 100
    assert factors == ["high_views", "very_recent", "ideal_duration"]


# ---------------------------------------------------------------------------
# 2. Old + low views + no duration = 0
# ---------------------------------------------------------------------------

def test_score_old_low_views():
    src = _src(view_count=500, published_at="2020-01-01", duration_seconds=None)
    score, factors = score_source(src, today=TODAY)
    assert score == 0
    assert factors == []


# ---------------------------------------------------------------------------
# 3. Missing view_count → no exception, views_score = 0
# ---------------------------------------------------------------------------

def test_score_missing_view_count():
    src = _src(view_count=None, published_at=None, duration_seconds=None)
    score, factors = score_source(src, today=TODAY)   # must not raise
    assert score == 0
    assert "high_views" not in factors
    assert "moderate_views" not in factors


# ---------------------------------------------------------------------------
# 4. Missing published_at → no exception, recency_score = 0
# ---------------------------------------------------------------------------

def test_score_missing_published_at():
    src = _src(view_count=100_000, published_at=None, duration_seconds=None)
    score, factors = score_source(src, today=TODAY)
    assert score == 40          # only views_score
    assert "high_views" in factors
    assert "very_recent" not in factors
    assert "recent" not in factors


# ---------------------------------------------------------------------------
# 5. Unparseable published_at → no exception, recency_score = 0
# ---------------------------------------------------------------------------

def test_score_unparseable_published_at():
    src = _src(view_count=None, published_at="not-a-date", duration_seconds=None)
    score, factors = score_source(src, today=TODAY)   # must not raise
    assert score == 0


# ---------------------------------------------------------------------------
# 6. Missing duration_seconds → no exception, duration_score = 0
# ---------------------------------------------------------------------------

def test_score_missing_duration():
    src = _src(view_count=None, published_at=None, duration_seconds=None)
    score, factors = score_source(src, today=TODAY)
    assert score == 0
    assert "ideal_duration" not in factors


# ---------------------------------------------------------------------------
# 7. Ideal duration (300-2400s) → 20 pts + label
# ---------------------------------------------------------------------------

def test_score_ideal_duration():
    src = _src(view_count=None, published_at=None, duration_seconds=900)   # 15 min
    score, factors = score_source(src, today=TODAY)
    assert score == 20
    assert "ideal_duration" in factors


# ---------------------------------------------------------------------------
# 8. Short duration (< 120s) → 0 pts, no label
# ---------------------------------------------------------------------------

def test_score_short_duration():
    src = _src(view_count=None, published_at=None, duration_seconds=60)
    score, factors = score_source(src, today=TODAY)
    assert score == 0
    assert "ideal_duration" not in factors


# ---------------------------------------------------------------------------
# 9. Boundary: exactly 30 days ago → very_recent (40 pts)
# ---------------------------------------------------------------------------

def test_score_boundary_30_days():
    pub = str(TODAY - timedelta(days=30))
    src = _src(view_count=None, published_at=pub, duration_seconds=None)
    score, factors = score_source(src, today=TODAY)
    assert score == 40
    assert "very_recent" in factors


# ---------------------------------------------------------------------------
# 10. Boundary: exactly 31 days ago → recent (30 pts), not very_recent
# ---------------------------------------------------------------------------

def test_score_boundary_31_days():
    pub = str(TODAY - timedelta(days=31))
    src = _src(view_count=None, published_at=pub, duration_seconds=None)
    score, factors = score_source(src, today=TODAY)
    assert score == 30
    assert "recent" in factors
    assert "very_recent" not in factors


# ---------------------------------------------------------------------------
# 11. quality_factors order: views, recency, duration
# ---------------------------------------------------------------------------

def test_quality_factors_order():
    pub = str(TODAY - timedelta(days=6))
    src = _src(view_count=100_000, published_at=pub, duration_seconds=900)
    _, factors = score_source(src, today=TODAY)
    assert factors == ["high_views", "very_recent", "ideal_duration"]


# ---------------------------------------------------------------------------
# 12. Partial factors: only one component contributes
# ---------------------------------------------------------------------------

def test_quality_factors_partial():
    src = _src(view_count=None, published_at=None, duration_seconds=900)
    _, factors = score_source(src, today=TODAY)
    assert factors == ["ideal_duration"]


# ---------------------------------------------------------------------------
# 13. Cap sorts by quality_score before view_count
# ---------------------------------------------------------------------------

def test_cap_sorts_by_score():
    high_score = _src(
        video_id="hi",
        view_count=5_000,
        published_at=str(TODAY - timedelta(days=6)),
        duration_seconds=900,
        quality_score=90,
        quality_factors=["very_recent", "ideal_duration"],
    )
    low_score = _src(
        video_id="lo",
        view_count=200_000,
        published_at="2020-01-01",
        duration_seconds=None,
        quality_score=8,
        quality_factors=[],
    )
    result = _filter1([high_score, low_score], cap=1)
    kept = [r for r in result if r["included"]]
    assert len(kept) == 1
    assert kept[0]["video_id"] == "hi"


# ---------------------------------------------------------------------------
# 14. Cap tiebreak: same quality_score → higher view_count wins
# ---------------------------------------------------------------------------

def test_cap_tiebreak_by_views():
    s1 = _src(video_id="hi_views", view_count=50_000, quality_score=8, quality_factors=[])
    s2 = _src(video_id="lo_views", view_count=10_000, quality_score=8, quality_factors=[])
    result = _filter1([s1, s2], cap=1)
    kept = [r for r in result if r["included"]]
    assert len(kept) == 1
    assert kept[0]["video_id"] == "hi_views"


# ---------------------------------------------------------------------------
# 15. curation_report.md includes Score and Factors columns
# ---------------------------------------------------------------------------

def test_curation_report_score_column(tmp_path):
    from notebooklm_orchestrator.cli import _write_curation_report

    sources = [_src(
        view_count=50_000,
        published_at=str(TODAY - timedelta(days=20)),
        duration_seconds=600,
        quality_score=75,
        quality_factors=["moderate_views", "very_recent"],
    )]
    report = tmp_path / "report.md"
    _write_curation_report(report, sources, "test query", ["briefing"])
    text = report.read_text()

    assert "| Score |" in text
    assert "| Factors |" in text
    assert "| 75 |" in text
    assert "moderate_views, very_recent" in text
