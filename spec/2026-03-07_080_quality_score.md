# Spec: Quality Scoring and Ranking for YouTube Sources
Date: 2026-03-07
Status: v1 (post-interview 2026-03-07)

---

## Goals

1. Compute a deterministic `quality_score` (int, 0-100) for every YouTube source using metadata already available after yt-dlp fetch.
2. Replace the selection cap's `view_count`-only sort with `quality_score DESC`, `view_count DESC`.
3. Record contributing factors as `quality_factors` (list of label strings) on every source.
4. Expose Score and Factors columns in `curation_report.md`.

## Non-goals

- No network calls for scoring.
- No new CLI flags.
- No changes to `notebooklm_cli.py`.
- No LLM-based or semantic quality assessment.
- Channel allow/block lists do not influence score (blocklisted sources are already excluded; allowlist bonus is non-differentiating within a run and has been removed).

---

## New source object fields

Added to **every** source in `sources.json` (included and excluded):

```json
{
  "quality_score": 72,
  "quality_factors": ["high_views", "very_recent", "ideal_duration"]
}
```

- `quality_score`: integer, always in [0, 100]. Never null.
- `quality_factors`: list of short ASCII label strings. Never null. Empty list `[]` when no component contributes a label.
- Both fields are always present, even when all input fields are null (defaults: `quality_score=0`, `quality_factors=[]`).

---

## Scoring formula

Three independent components. Sum clamped to [0, 100] (in practice, max is exactly 100).

### Component 1: views_score (0-40)

Piecewise on `view_count` (int or null):

| view_count | points | quality_factors label |
|---|---|---|
| >= 100,000 | 40 | `high_views` |
| >= 10,000 | 20 | `moderate_views` |
| >= 1,000 | 8 | (none) |
| < 1,000 or null | 0 | (none) |

### Component 2: recency_score (0-40)

Piecewise on age in whole days from `published_at` to `today` (the scoring date):

| age in days | points | quality_factors label |
|---|---|---|
| <= 30 | 40 | `very_recent` |
| <= 90 | 30 | `recent` |
| <= 180 | 20 | (none) |
| <= 365 | 10 | (none) |
| <= 730 | 4 | (none) |
| > 730 or null | 0 | (none) |

`published_at` is in `YYYY-MM-DD` format (set by `_parse_entry`). If null or unparseable: recency_score = 0, no label.

Age calculation: `(today - date.fromisoformat(published_at)).days`. Boundary is inclusive (age == 30 → "very_recent").

### Component 3: duration_score (0-20)

Piecewise on `duration_seconds` (int or null):

| duration_seconds | points | quality_factors label |
|---|---|---|
| 300-2400 (5-40 min) | 20 | `ideal_duration` |
| 120-299 (2-5 min) | 8 | (none) |
| 2401-3600 (40-60 min) | 8 | (none) |
| < 120 or > 3600 or null | 0 | (none) |

### Total

`quality_score = min(100, views_score + recency_score + duration_score)`

Max achievable: 40 + 40 + 20 = 100.

---

## `quality_factors` ordering and truncation

`quality_factors` list is always in this fixed order (omit absent labels):
1. Views label (`high_views`, `moderate_views`) -- or absent
2. Recency label (`very_recent`, `recent`) -- or absent
3. Duration label (`ideal_duration`) -- or absent

Maximum 3 labels possible (one per component). The list is never truncated in `sources.json`.

In `curation_report.md` the Factors column shows up to 3 labels comma-separated. If `quality_factors` is empty: display `-`.

---

## `score_source` function

New standalone function in `sources.py`:

```python
def score_source(source: dict, *, today: date) -> tuple[int, list[str]]:
    """
    Compute (quality_score, quality_factors) for a single normalized source dict.

    today: reference date injected by caller (use date.today() in curate_sources).
    Never raises; returns (0, []) on any missing/unparseable input.
    """
```

- Takes the normalized source dict (output of `_parse_entry`).
- `today` is injected so tests can fix the reference date without monkeypatching.
- Never raises an exception regardless of input.
- Returns `(int, list[str])`.

---

## Scoring location in pipeline

Scoring is called from `curate_sources`, **before** `apply_filters`:

```python
# In curate_sources, after parsing raw entries:
today = date.today()
for entry in entries:
    entry["quality_score"], entry["quality_factors"] = score_source(entry, today=today)

# Then apply_filters (unchanged signature):
items = apply_filters(entries, ...)
```

`apply_filters` signature is **unchanged**. It receives entries that already have `quality_score` set.

---

## Selection cap change (inside `apply_filters`)

Step 7 of `apply_filters` currently:
```python
included.sort(key=lambda x: x.get("view_count") if x.get("view_count") is not None else -1, reverse=True)
```

New:
```python
included.sort(key=lambda x: (x.get("quality_score", 0), x.get("view_count") or 0), reverse=True)
```

Primary sort: `quality_score DESC`. Tiebreak: `view_count DESC`. No other change to `apply_filters`.

Backward compatibility: existing `test_sources.py` tests call `apply_filters` directly with entries that lack `quality_score`. `x.get("quality_score", 0)` returns 0 for all, so tiebreak falls to `view_count`, preserving existing test behavior.

---

## `curation_report.md` change

The included sources table gains two columns after `Published`:

```
| # | Title | Channel | Views | Duration | Published | Score | Factors | URL | Notes |
```

- `Score`: integer, e.g. `72`.
- `Factors`: `quality_factors` joined with `, `. Max 3 labels (list is always <= 3 items; no truncation needed). Empty → `-`.

`_write_curation_report` in `cli.py` must be updated. The column order must match exactly.

---

## Missing/null field handling

| Field | Behavior |
|---|---|
| `view_count` null | views_score = 0; no label |
| `published_at` null | recency_score = 0; no label |
| `published_at` unparseable | recency_score = 0; no label (do not raise) |
| `duration_seconds` null | duration_score = 0; no label |
| All fields null | quality_score = 0; quality_factors = [] |

---

## Acceptance criteria

1. Every source in `sources.json` has `quality_score` (int in [0, 100]) and `quality_factors` (list of strings).
2. Excluded sources also have both fields set (not zero-defaulted).
3. Score is deterministic: same source dict + same `today` always produces the same `(score, factors)`.
4. A source with higher `quality_score` is selected over a lower-score source at the cap, regardless of view count.
5. Tie on `quality_score`: higher `view_count` wins. Tie on both: original order preserved (stable sort).
6. `quality_factors` labels are exactly the strings defined in this spec (`high_views`, `moderate_views`, `very_recent`, `recent`, `ideal_duration`). No freeform text.
7. `quality_factors` order is always: views label first, recency label second, duration label third.
8. `score_source` never raises, regardless of input.
9. `curation_report.md` includes `Score` and `Factors` columns; empty factors display `-`.
10. `apply_filters` signature is unchanged; existing tests pass without modification.

---

## Tests required (minimum 12, all no-network)

New test file: `tests/test_quality_score.py`. All tests import `score_source` directly and call with a fixed `today`.

| Test | Description |
|---|---|
| `test_score_high_views_recent_ideal` | >=100k views + <=30 days + 5-40 min = score 100 |
| `test_score_old_low_views` | < 1k views + > 730 days + null duration = score 0 |
| `test_score_missing_view_count` | view_count=None: no exception, views_score=0 |
| `test_score_missing_published_at` | published_at=None: no exception, recency_score=0 |
| `test_score_unparseable_published_at` | published_at="not-a-date": no exception, recency_score=0 |
| `test_score_missing_duration` | duration_seconds=None: no exception, duration_score=0 |
| `test_score_ideal_duration` | 300-2400s gets 20 pts; `ideal_duration` in factors |
| `test_score_short_duration` | < 120s gets 0 pts; no duration label |
| `test_score_boundary_30_days` | age exactly 30 days = very_recent (40 pts) |
| `test_score_boundary_31_days` | age exactly 31 days = recent (30 pts), not very_recent |
| `test_quality_factors_order` | factors list always: views label, recency label, duration label |
| `test_quality_factors_partial` | only one component contributes: list has exactly one element |
| `test_cap_sorts_by_score` | in apply_filters, higher-score source is kept over lower-score at cap |
| `test_cap_tiebreak_by_views` | same quality_score, higher view_count wins the cap |
| `test_curation_report_score_column` | curation_report.md includes `Score` and `Factors` column headers |

---

## Rollout

- Implement in `sources.py`: add `score_source`; call it in `curate_sources` before `apply_filters`; update cap sort in `apply_filters`.
- Update `cli.py`: add Score and Factors columns to `_write_curation_report`.
- New test file: `tests/test_quality_score.py`.
- Existing `tests/test_sources.py` and `tests/test_review.py` require no changes.

---

## Decision log

- 2026-03-07 (draft): Metadata-only scoring. No network calls. No LLM scoring.
- 2026-03-07 (interview): View tiers collapsed to 3 (>=100k=40, >=10k=20, >=1k=8). Simpler; matches typical distribution.
- 2026-03-07 (interview): Channel bonus removed. Non-differentiating when allowlist is configured (all included sources pass). No dead code.
- 2026-03-07 (interview): Points redistributed to views=40, recency=40, duration=20. Recency promoted to equal weight with views.
- 2026-03-07 (interview): score_source called from curate_sources before apply_filters. apply_filters signature unchanged.
- 2026-03-07 (interview): All sources scored (included and excluded). Useful for --review mode: reinstated sources show their score.
- 2026-03-07 (interview): Recency labels: <=30d="very_recent", <=90d="recent", <=180d=no label.
- 2026-03-07 (interview): Duration ideal range widened to 5-40 min (300-2400s). Covers quick overviews and extended walkthroughs.

---

## Remaining open questions

None. All blocking questions resolved in interview.
