"""YouTube source collection and curation via yt-dlp."""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# Default selection cap: max sources marked included=true after all filters.
# Distinct from --max-results (yt-dlp fetch cap). NotebookLM hard cap is 50.
SELECTION_CAP = 20

# Keys that must be present and non-null in a yt-dlp JSON object for the
# probe to consider the invocation mode adequate.
_PROBE_REQUIRED = ("id", "title", "view_count", "upload_date")
_PROBE_DURATION_KEYS = ("duration", "duration_seconds")


# ---------------------------------------------------------------------------
# yt-dlp helpers
# ---------------------------------------------------------------------------

def get_ytdlp_version(ytdlp_path: str) -> str:
    try:
        r = subprocess.run(
            [ytdlp_path, "--version"],
            capture_output=True, text=True, timeout=15,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _build_cmd(ytdlp_path: str, query: str, max_results: int, flat_playlist: bool) -> list[str]:
    cmd = [ytdlp_path, "--dump-json"]
    if flat_playlist:
        cmd.append("--flat-playlist")
    cmd.append(f"ytsearch{max_results}:{query}")
    return cmd


def _has_required_fields(obj: dict) -> bool:
    """Return True if all required metadata keys are present and non-null."""
    for key in _PROBE_REQUIRED:
        if obj.get(key) is None:
            return False
    has_duration = any(obj.get(k) is not None for k in _PROBE_DURATION_KEYS)
    return has_duration


def probe_metadata_mode(ytdlp_path: str, query: str) -> tuple[bool, bool]:
    """
    Probe yt-dlp with ytsearch5 to determine if --flat-playlist returns
    required metadata fields.

    Returns (use_flat_playlist: bool, probe_succeeded: bool).
    If probe_succeeded is False, the real run should still proceed using
    flat_playlist=False as the safer default.
    """
    for flat_playlist in (True, False):
        cmd = _build_cmd(ytdlp_path, query, 5, flat_playlist)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        except subprocess.TimeoutExpired:
            continue
        if r.returncode != 0:
            # yt-dlp errored; try other mode before giving up on probe
            continue
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _has_required_fields(obj):
                return flat_playlist, True
            # First parseable object checked; if fields missing, try other mode
            break

    # Could not verify fields in either mode; default to full metadata (safer)
    return False, False


def _run_ytdlp(
    cmd: list[str],
    raw_path: Path,
    log_path: Path,
) -> tuple[int, list[str]]:
    """
    Run yt-dlp command. On non-zero exit, wait 3s and retry once.
    Writes stdout lines to raw_path. Appends stderr to log_path.
    Returns (exit_code, stdout_lines).
    """
    for attempt in range(2):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            _append_log(log_path, "yt-dlp timed out after 300s.")
            if attempt == 0:
                time.sleep(3)
                continue
            return 1, []

        if r.stderr:
            _append_log(log_path, r.stderr.rstrip())

        if r.returncode == 0:
            lines = [l for l in r.stdout.splitlines() if l.strip()]
            raw_path.write_text(r.stdout, encoding="utf-8")
            return 0, lines

        _append_log(log_path, f"yt-dlp exited {r.returncode} (attempt {attempt + 1}/2).")
        if attempt == 0:
            time.sleep(3)

    raw_path.touch()
    return 1, []


def _append_log(log_path: Path, message: str) -> None:
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(message + "\n")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize_entry(raw: dict) -> dict:
    """Normalize a yt-dlp JSON object to the canonical sources.json schema."""
    video_id = raw.get("id") or ""

    # URL: prefer webpage_url; fall back to url; construct from id if needed
    url = raw.get("webpage_url") or raw.get("url") or ""
    if url and not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={video_id}"
    if not url and video_id:
        url = f"https://www.youtube.com/watch?v={video_id}"

    # published_at: yt-dlp upload_date is "YYYYMMDD"
    upload_date = raw.get("upload_date")
    published_at: Optional[str] = None
    if upload_date:
        s = str(upload_date)
        if len(s) == 8 and s.isdigit():
            published_at = f"{s[:4]}-{s[4:6]}-{s[6:8]}"

    # duration_seconds: yt-dlp key is "duration" (float or int, seconds)
    duration_raw = raw.get("duration") if raw.get("duration") is not None else raw.get("duration_seconds")
    duration_seconds: Optional[int] = int(duration_raw) if duration_raw is not None else None

    # view_count
    vc_raw = raw.get("view_count")
    view_count: Optional[int] = int(vc_raw) if vc_raw is not None else None

    # channel
    channel = raw.get("channel") or raw.get("uploader") or raw.get("channel_id") or ""

    return {
        "type": "youtube",
        "video_id": video_id,
        "title": raw.get("title") or "",
        "url": url,
        "channel": channel,
        "view_count": view_count,
        "duration_seconds": duration_seconds,
        "published_at": published_at,
        "included": True,
        "exclusion_reason": None,
    }


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------

def score_source(entry: dict, *, today: date) -> tuple[int, list[str]]:
    """Return (quality_score, quality_factors) for a normalized source dict.

    today: reference date for recency (injected so tests can fix it).
    Never raises; returns (0, []) when all fields are missing/unparseable.
    """
    factors: list[str] = []
    views_score = 0
    recency_score = 0
    duration_score = 0

    # Component 1: views (0-40)
    vc = entry.get("view_count")
    if vc is not None:
        try:
            vc = int(vc)
            if vc >= 100_000:
                views_score = 40
                factors.append("high_views")
            elif vc >= 10_000:
                views_score = 20
                factors.append("moderate_views")
            elif vc >= 1_000:
                views_score = 8
        except (TypeError, ValueError):
            pass

    # Component 2: recency (0-40)
    pub = entry.get("published_at")
    if pub is not None:
        try:
            age_days = (today - date.fromisoformat(str(pub))).days
            if age_days <= 30:
                recency_score = 40
                factors.append("very_recent")
            elif age_days <= 90:
                recency_score = 30
                factors.append("recent")
            elif age_days <= 180:
                recency_score = 20
            elif age_days <= 365:
                recency_score = 10
            elif age_days <= 730:
                recency_score = 4
        except (ValueError, TypeError, OverflowError):
            pass

    # Component 3: duration (0-20)
    dur = entry.get("duration_seconds")
    if dur is not None:
        try:
            dur = int(dur)
            if 300 <= dur <= 2400:
                duration_score = 20
                factors.append("ideal_duration")
            elif 120 <= dur < 300 or 2400 < dur <= 3600:
                duration_score = 8
        except (TypeError, ValueError):
            pass

    score = min(100, views_score + recency_score + duration_score)
    return score, factors


# ---------------------------------------------------------------------------
# Filter value parsing
# ---------------------------------------------------------------------------

def parse_recency(value: str) -> Optional[date]:
    """Parse recency string to a cutoff date. Returns None for 'all'."""
    if value == "all":
        return None
    m = re.fullmatch(r"(\d+)(d|months|years)", value)
    if not m:
        raise ValueError(
            f"Invalid --recency value: {value!r}. Expected Nd, Nmonths, Nyears, or all."
        )
    n, unit = int(m.group(1)), m.group(2)
    if unit == "d":
        delta = timedelta(days=n)
    elif unit == "months":
        delta = timedelta(days=n * 30)
    else:
        delta = timedelta(days=n * 365)
    return (datetime.now() - delta).date()


def parse_duration(value: str) -> Optional[int]:
    """Parse duration string to seconds. Returns None for 'all'."""
    if value == "all":
        return None
    m = re.fullmatch(r"(\d+)(m|h)", value)
    if not m:
        raise ValueError(
            f"Invalid --max-duration value: {value!r}. Expected Nm or Nh."
        )
    n, unit = int(m.group(1)), m.group(2)
    return n * 60 if unit == "m" else n * 3600


# ---------------------------------------------------------------------------
# Filter pipeline
# ---------------------------------------------------------------------------

def apply_filters(
    entries: list[dict],
    *,
    channel_allow: Optional[str],
    channel_block: Optional[str],
    recency: str,
    max_duration: str,
    min_views: int,
    selection_cap: int = SELECTION_CAP,
) -> list[dict]:
    """
    Apply filters in spec-defined order. Returns all entries with
    included and exclusion_reason fields set. Does not mutate input dicts.
    """
    recency_cutoff = parse_recency(recency)
    max_dur_secs = parse_duration(max_duration)

    allow_list = [c.strip().lower() for c in channel_allow.split(",")] if channel_allow else []
    block_list = [c.strip().lower() for c in channel_block.split(",")] if channel_block else []

    items = [dict(e) for e in entries]  # shallow copies

    # 1. channel_allow
    if allow_list:
        for item in items:
            if item["included"] and (item.get("channel") or "").lower() not in allow_list:
                item["included"] = False
                item["exclusion_reason"] = "channel_allow"

    # 2. channel_block
    if block_list:
        for item in items:
            if item["included"] and (item.get("channel") or "").lower() in block_list:
                item["included"] = False
                item["exclusion_reason"] = "channel_block"

    # 3. recency (null published_at → exclude)
    if recency_cutoff is not None:
        for item in items:
            if not item["included"]:
                continue
            pub = item.get("published_at")
            if pub is None:
                item["included"] = False
                item["exclusion_reason"] = "recency"
            else:
                try:
                    if date.fromisoformat(pub) < recency_cutoff:
                        item["included"] = False
                        item["exclusion_reason"] = "recency"
                except ValueError:
                    item["included"] = False
                    item["exclusion_reason"] = "recency"

    # 4. max_duration (null duration_seconds → exclude)
    if max_dur_secs is not None:
        for item in items:
            if not item["included"]:
                continue
            dur = item.get("duration_seconds")
            if dur is None or dur > max_dur_secs:
                item["included"] = False
                item["exclusion_reason"] = "max_duration"

    # 5. min_views (null view_count → exclude)
    for item in items:
        if not item["included"]:
            continue
        vc = item.get("view_count")
        if vc is None or vc < min_views:
            item["included"] = False
            item["exclusion_reason"] = "min_views"

    # 6. dedupe by video_id (among currently included items only)
    seen: dict[str, dict] = {}  # video_id -> best item kept so far
    for item in items:
        if not item["included"]:
            continue
        vid = item.get("video_id") or ""
        if not vid:
            continue
        if vid not in seen:
            seen[vid] = item
        else:
            prev = seen[vid]
            prev_date = prev.get("published_at")
            curr_date = item.get("published_at")
            # Keep newer; on tie or missing date, keep higher view_count
            keep_current = False
            if prev_date and curr_date and prev_date != curr_date:
                keep_current = curr_date > prev_date
            else:
                keep_current = (item.get("view_count") or 0) > (prev.get("view_count") or 0)

            if keep_current:
                prev["included"] = False
                prev["exclusion_reason"] = "duplicate"
                seen[vid] = item
            else:
                item["included"] = False
                item["exclusion_reason"] = "duplicate"

    # 7. cap: keep top `selection_cap` included items by quality_score desc, view_count desc
    included = [item for item in items if item["included"]]
    included.sort(
        key=lambda x: (x.get("quality_score", 0), x.get("view_count") or 0),
        reverse=True,
    )
    keep_ids = {id(item) for item in included[:selection_cap]}
    for item in included[selection_cap:]:
        item["included"] = False
        item["exclusion_reason"] = "cap"

    return items


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def curate_sources(
    *,
    ytdlp_path: str,
    query: str,
    max_results: int,
    recency: str,
    max_duration: str,
    min_views: int,
    channel_allow: Optional[str],
    channel_block: Optional[str],
    raw_path: Path,
    sources_path: Path,
    log_path: Path,
) -> dict:
    """
    Full YouTube curation pipeline.

    Returns a result dict suitable for embedding in run_manifest.json.
    Does not call sys.exit(); exit_code field carries the intended exit code.
    """
    started_at = datetime.now().isoformat(timespec="seconds")

    # Cap fetch count at NotebookLM hard limit
    if max_results > 50:
        _append_log(log_path, f"Warning: --max-results {max_results} exceeds cap; clamped to 50.")
        max_results = 50

    version = get_ytdlp_version(ytdlp_path)
    _append_log(log_path, f"yt-dlp version: {version}")

    # Probe: determine if --flat-playlist returns required metadata fields
    _append_log(log_path, "Probing yt-dlp metadata mode (ytsearch5)...")
    use_flat, probe_ok = probe_metadata_mode(ytdlp_path, query)
    if probe_ok:
        mode = "flat-playlist" if use_flat else "full-metadata"
        _append_log(log_path, f"Probe OK: using {mode} mode.")
    else:
        _append_log(
            log_path,
            "Probe could not verify required metadata fields in either mode. "
            "Proceeding with full-metadata mode (no --flat-playlist).",
        )
        use_flat = False

    # Build the real command
    cmd = _build_cmd(ytdlp_path, query, max_results, use_flat)
    cmd_str = " ".join(cmd)
    _append_log(log_path, f"Running: {cmd_str}")

    # Run with retry
    exit_code, raw_lines = _run_ytdlp(cmd, raw_path, log_path)

    if exit_code != 0:
        _append_log(log_path, "yt-dlp failed after retry. Aborting.")
        return {
            "yt_dlp_version": version,
            "yt_dlp_command": cmd_str,
            "candidate_count": 0,
            "included_count": 0,
            "excluded_count": 0,
            "status": "failed",
            "exit_code": 1,
            "error_summary": "yt-dlp exited non-zero after retry. Check run.log.",
            "started_at": started_at,
        }

    # Parse and normalize
    entries: list[dict] = []
    parse_errors = 0
    for line in raw_lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        entries.append(normalize_entry(obj))

    if parse_errors:
        _append_log(log_path, f"Warning: {parse_errors} line(s) in raw.jsonl could not be parsed.")

    candidate_count = len(entries)
    _append_log(log_path, f"Candidates fetched: {candidate_count}")

    # Score all entries before filtering
    today = date.today()
    for entry in entries:
        entry["quality_score"], entry["quality_factors"] = score_source(entry, today=today)

    # Apply filter pipeline
    filters = {
        "channel_allow": channel_allow,
        "channel_block": channel_block,
        "recency": recency,
        "max_duration": max_duration,
        "min_views": min_views,
        "selection_cap": SELECTION_CAP,
    }
    filtered = apply_filters(
        entries,
        channel_allow=channel_allow,
        channel_block=channel_block,
        recency=recency,
        max_duration=max_duration,
        min_views=min_views,
    )

    included_count = sum(1 for e in filtered if e["included"])
    excluded_count = candidate_count - included_count

    _append_log(log_path, f"Included after filtering: {included_count} / {candidate_count}")

    # Write sources.json with header metadata + all source entries
    sources_doc = {
        "query": query,
        "filters_used": filters,
        "yt_dlp_version": version,
        "yt_dlp_command": cmd_str,
        "candidate_count": candidate_count,
        "included_count": included_count,
        "excluded_count": excluded_count,
        "sources": filtered,
    }
    sources_path.write_text(json.dumps(sources_doc, indent=2), encoding="utf-8")

    if included_count == 0:
        msg = (
            "No sources matched filters. "
            "Try relaxing --recency, --min-views, or --max-duration."
        )
        _append_log(log_path, msg)
        print(msg, flush=True)
        return {
            "yt_dlp_version": version,
            "yt_dlp_command": cmd_str,
            "candidate_count": candidate_count,
            "included_count": 0,
            "excluded_count": excluded_count,
            "status": "partial",
            "exit_code": 3,
            "error_summary": msg,
            "started_at": started_at,
        }

    return {
        "yt_dlp_version": version,
        "yt_dlp_command": cmd_str,
        "candidate_count": candidate_count,
        "included_count": included_count,
        "excluded_count": excluded_count,
        "status": "success",
        "exit_code": 0,
        "error_summary": None,
        "started_at": started_at,
    }
