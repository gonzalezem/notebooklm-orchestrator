"""Unit tests for notebooklm_orchestrator.sources."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from notebooklm_orchestrator.sources import (
    SELECTION_CAP,
    apply_filters,
    normalize_entry,
    parse_duration,
    parse_recency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(
    video_id: str = "vid1",
    title: str = "Test Video",
    channel: str = "TestChannel",
    view_count: int | None = 5000,
    duration: int | None = 600,   # seconds
    upload_date: str | None = None,
    url: str | None = None,
) -> dict:
    """Build a minimal fake yt-dlp JSON object and normalize it."""
    if upload_date is None:
        # Default: 30 days ago, well within any default recency window
        d = datetime.now() - timedelta(days=30)
        upload_date = d.strftime("%Y%m%d")
    raw = {
        "id": video_id,
        "title": title,
        "channel": channel,
        "view_count": view_count,
        "duration": duration,
        "upload_date": upload_date,
        "webpage_url": url or f"https://www.youtube.com/watch?v={video_id}",
    }
    return normalize_entry(raw)


def _run_filters(entries, **kwargs) -> list[dict]:
    defaults = dict(
        channel_allow=None,
        channel_block=None,
        recency="all",
        max_duration="all",
        min_views=0,
        selection_cap=SELECTION_CAP,
    )
    defaults.update(kwargs)
    return apply_filters(entries, **defaults)


# ---------------------------------------------------------------------------
# 1. parse_recency
# ---------------------------------------------------------------------------

def test_parse_recency_6months():
    cutoff = parse_recency("6months")
    expected = (datetime.now() - timedelta(days=6 * 30)).date()
    assert cutoff is not None
    assert abs((cutoff - expected).days) <= 1


def test_parse_recency_90d():
    cutoff = parse_recency("90d")
    expected = (datetime.now() - timedelta(days=90)).date()
    assert cutoff is not None
    assert abs((cutoff - expected).days) <= 1


def test_parse_recency_all():
    assert parse_recency("all") is None


def test_parse_recency_invalid():
    with pytest.raises(ValueError):
        parse_recency("6weeks")


# ---------------------------------------------------------------------------
# 2. parse_duration
# ---------------------------------------------------------------------------

def test_parse_duration_30m():
    assert parse_duration("30m") == 1800


def test_parse_duration_1h():
    assert parse_duration("1h") == 3600


def test_parse_duration_90m():
    assert parse_duration("90m") == 5400


def test_parse_duration_all():
    assert parse_duration("all") is None


def test_parse_duration_invalid():
    with pytest.raises(ValueError):
        parse_duration("2days")


# ---------------------------------------------------------------------------
# 3. min_views filter with null view_count
# ---------------------------------------------------------------------------

def test_filter_min_views_null_excluded():
    """Null view_count is excluded with exclusion_reason='min_views'."""
    entries = [_entry(video_id="a", view_count=None)]
    result = _run_filters(entries, min_views=1000)
    assert result[0]["included"] is False
    assert result[0]["exclusion_reason"] == "min_views"


def test_filter_min_views_below_threshold():
    entries = [_entry(video_id="b", view_count=500)]
    result = _run_filters(entries, min_views=1000)
    assert result[0]["included"] is False
    assert result[0]["exclusion_reason"] == "min_views"


def test_filter_min_views_passes():
    entries = [_entry(video_id="c", view_count=2000)]
    result = _run_filters(entries, min_views=1000)
    assert result[0]["included"] is True


# ---------------------------------------------------------------------------
# 4. cap keeps top by view_count
# ---------------------------------------------------------------------------

def test_cap_keeps_top_by_view_count():
    """With 25 entries and selection_cap=20, top 20 by view_count are included."""
    entries = [_entry(video_id=f"v{i}", view_count=i * 1000) for i in range(25)]
    result = _run_filters(entries, selection_cap=20)

    included = [e for e in result if e["included"]]
    capped = [e for e in result if e["exclusion_reason"] == "cap"]

    assert len(included) == 20
    assert len(capped) == 5
    # All included items have higher view_count than all capped items
    min_included_vc = min(e["view_count"] for e in included)
    max_capped_vc = max(e["view_count"] for e in capped)
    assert min_included_vc > max_capped_vc


def test_cap_null_view_count_excluded_by_min_views_before_cap():
    """
    Null view_count is excluded at the min_views filter stage (step 5), not
    the cap stage (step 7). Even min_views=0 excludes null because the check
    is 'vc is None or vc < threshold'. The cap never sees null-view entries.
    """
    entries = [_entry(video_id="null_vc", view_count=None)] + [
        _entry(video_id=f"v{i}", view_count=i * 100 + 1) for i in range(5)
    ]
    result = _run_filters(entries, min_views=0, selection_cap=5)
    null_entry = next(e for e in result if e["video_id"] == "null_vc")
    assert null_entry["included"] is False
    assert null_entry["exclusion_reason"] == "min_views"  # eliminated before cap stage


# ---------------------------------------------------------------------------
# 5. dedupe behavior
# ---------------------------------------------------------------------------

def test_dedupe_keeps_newer_by_date():
    """Duplicate video_id: entry with more recent upload_date wins."""
    old = _entry(video_id="dup", view_count=10000, upload_date="20240101")
    new = _entry(video_id="dup", view_count=3000, upload_date="20260101")
    result = _run_filters([old, new])

    included = [e for e in result if e["included"]]
    duped = [e for e in result if e["exclusion_reason"] == "duplicate"]
    assert len(included) == 1
    assert len(duped) == 1
    assert included[0]["published_at"] == "2026-01-01"


def test_dedupe_keeps_higher_views_on_date_tie():
    """Duplicate video_id with same date: higher view_count wins."""
    low = _entry(video_id="dup", view_count=1000, upload_date="20260101")
    high = _entry(video_id="dup", view_count=9000, upload_date="20260101")
    result = _run_filters([low, high])

    included = [e for e in result if e["included"]]
    assert len(included) == 1
    assert included[0]["view_count"] == 9000


# ---------------------------------------------------------------------------
# 6. channel allow / block
# ---------------------------------------------------------------------------

def test_channel_block_excludes_matching():
    entries = [
        _entry(video_id="bad", channel="SpamChannel"),
        _entry(video_id="good", channel="GoodChannel"),
    ]
    result = _run_filters(entries, channel_block="SpamChannel")
    blocked = [e for e in result if e["exclusion_reason"] == "channel_block"]
    included = [e for e in result if e["included"]]
    assert len(blocked) == 1
    assert blocked[0]["video_id"] == "bad"
    assert len(included) == 1
    assert included[0]["video_id"] == "good"


def test_channel_block_case_insensitive():
    entries = [_entry(video_id="x", channel="MyChannel")]
    result = _run_filters(entries, channel_block="mychannel")
    assert result[0]["included"] is False
    assert result[0]["exclusion_reason"] == "channel_block"


def test_channel_allow_excludes_non_matching():
    entries = [
        _entry(video_id="allowed", channel="TrustedChannel"),
        _entry(video_id="other", channel="RandomChannel"),
    ]
    result = _run_filters(entries, channel_allow="TrustedChannel")
    excluded = [e for e in result if e["exclusion_reason"] == "channel_allow"]
    included = [e for e in result if e["included"]]
    assert len(excluded) == 1
    assert excluded[0]["video_id"] == "other"
    assert len(included) == 1
    assert included[0]["video_id"] == "allowed"


def test_channel_block_applied_before_allow():
    """A channel in both block and allow lists is blocked (block runs first)."""
    entries = [_entry(video_id="z", channel="AmbiguousChannel")]
    result = _run_filters(
        entries,
        channel_allow="AmbiguousChannel",
        channel_block="AmbiguousChannel",
    )
    assert result[0]["included"] is False
    assert result[0]["exclusion_reason"] == "channel_block"


# ---------------------------------------------------------------------------
# 7. recency filter
# ---------------------------------------------------------------------------

def test_recency_excludes_old_entry():
    old_date = (datetime.now() - timedelta(days=400)).strftime("%Y%m%d")
    entries = [_entry(video_id="old", upload_date=old_date)]
    result = _run_filters(entries, recency="6months")
    assert result[0]["included"] is False
    assert result[0]["exclusion_reason"] == "recency"


def test_recency_null_published_at_excluded():
    """Null published_at is excluded under recency filter (not invented)."""
    raw = {
        "id": "nopub", "title": "No Date", "channel": "Chan",
        "view_count": 9999, "duration": 300, "upload_date": None,
        "webpage_url": "https://www.youtube.com/watch?v=nopub",
    }
    entries = [normalize_entry(raw)]
    result = _run_filters(entries, recency="6months")
    assert result[0]["included"] is False
    assert result[0]["exclusion_reason"] == "recency"


# ---------------------------------------------------------------------------
# 8. max_duration filter
# ---------------------------------------------------------------------------

def test_max_duration_excludes_long_video():
    entries = [_entry(video_id="long", duration=7200)]  # 2 hours
    result = _run_filters(entries, max_duration="30m")
    assert result[0]["included"] is False
    assert result[0]["exclusion_reason"] == "max_duration"


def test_max_duration_null_excluded():
    """Null duration_seconds excluded under max_duration filter."""
    raw = {
        "id": "nodur", "title": "No Duration", "channel": "Chan",
        "view_count": 9999, "duration": None, "upload_date": "20260101",
        "webpage_url": "https://www.youtube.com/watch?v=nodur",
    }
    entries = [normalize_entry(raw)]
    result = _run_filters(entries, max_duration="30m")
    assert result[0]["included"] is False
    assert result[0]["exclusion_reason"] == "max_duration"


# ---------------------------------------------------------------------------
# 9. normalize_entry
# ---------------------------------------------------------------------------

def test_normalize_constructs_url_from_id():
    raw = {"id": "abc123", "title": "T", "view_count": 1, "duration": 60}
    entry = normalize_entry(raw)
    assert entry["url"] == "https://www.youtube.com/watch?v=abc123"


def test_normalize_converts_upload_date():
    raw = {"id": "x", "upload_date": "20260305", "title": "T"}
    entry = normalize_entry(raw)
    assert entry["published_at"] == "2026-03-05"


def test_normalize_uses_uploader_fallback():
    raw = {"id": "x", "title": "T", "uploader": "FallbackChannel"}
    entry = normalize_entry(raw)
    assert entry["channel"] == "FallbackChannel"
