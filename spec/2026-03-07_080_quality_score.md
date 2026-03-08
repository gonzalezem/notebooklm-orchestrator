# Spec: Quality Scoring and Ranking for YouTube Sources
Date: 2026-03-07
Status: draft (pre-interview)

---

## Problem

The selection cap (SELECTION_CAP=20) currently picks the top 20 sources by `view_count` only. View count alone is a poor quality signal: a 5-year-old viral video outranks a recent, well-produced 30-minute tutorial. Sources passed to NotebookLM should be the best quality within the curated set, not just the most-watched.

---

## Proposed feature

Compute a deterministic `quality_score` (int, 0-100) for every YouTube source using metadata fields already available after yt-dlp fetch. Use `quality_score` (then `view_count`) as the sort key for the selection cap. Record the contributing factors as `quality_factors` (list of short label strings) on each source object.

---

## Scope

- `sources.py` only. No changes to `notebooklm_cli.py`, `cli.py`, or `pyproject.toml`.
- One exception: `cli.py`'s `_write_curation_report` must be updated to add Score and Factors columns to `curation_report.md`.
- No network calls.
- No new CLI flags.

---

## New source object fields

Added to every source in `sources.json` (included and excluded):

```json
{
  "quality_score": 72,
  "quality_factors": ["high_views", "recent", "ideal_duration"]
}
```

- `quality_score`: integer in [0, 100]. Deterministic for a given set of inputs.
- `quality_factors`: list of short ASCII label strings describing which components contributed positively. Order: views label first, then recency label, then duration label, then channel label. Empty list if no factors contribute.
- Both fields are always present (not null). Default: `quality_score=0`, `quality_factors=[]` when all inputs are missing/null.

---

## Scoring formula

Four components. Total max = 100. Each component is computed independently; results summed and clamped to [0, 100].

### Component 1: views_score (0-40)

Piecewise on `view_count` (int or null):

| view_count | points | quality_factors label |
|---|---|---|
| >= 500,000 | 40 | `very_high_views` |
| >= 100,000 | 32 | `high_views` |
| >= 50,000 | 22 | `moderate_views` |
| >= 10,000 | 12 | `some_views` |
| >= 1,000 | 4 | (none) |
| < 1,000 or null | 0 | (none) |

Open question: are the breakpoints right, or should they be adjusted based on typical YouTube search result distributions?

### Component 2: recency_score (0-35)

Piecewise on age in days from `published_at` to the scoring date (today at run time):

| age | points | quality_factors label |
|---|---|---|
| <= 30 days | 35 | `very_recent` |
| <= 90 days | 28 | `recent` |
| <= 180 days | 20 | `recent` |
| <= 365 days | 12 | (none) |
| <= 730 days | 4 | (none) |
| > 730 days or null | 0 | (none) |

`published_at` is in `YYYY-MM-DD` format (set by `_parse_entry` in `sources.py`). If null or unparseable: recency_score = 0.

Open question: should the `<= 90 days` and `<= 180 days` brackets both use `"recent"` label, or distinguish them?

### Component 3: duration_score (0-15)

Piecewise on `duration_seconds` (int or null). Rationale: very short content lacks depth; very long content is rarely fully indexed. Sweet spot is informational tutorial range.

| duration_seconds | points | quality_factors label |
|---|---|---|
| 480-1500 (8-25 min) | 15 | `ideal_duration` |
| 300-479 (5-8 min) | 8 | (none) |
| 1501-2700 (25-45 min) | 8 | (none) |
| 120-299 (2-5 min) | 3 | (none) |
| 2701-3600 (45-60 min) | 3 | (none) |
| < 120s or > 3600s or null | 0 | (none) |

Open question: should the 8-25 min range be wider or narrower? Should we also give a label to the near-ideal brackets?

### Component 4: channel_bonus (0-10)

Only applies when `--channel-allow` is configured:

| condition | points | quality_factors label |
|---|---|---|
| `channel_allow` is set AND source channel matches an entry (case-insensitive) | 10 | `allowlisted_channel` |
| `channel_allow` is not set, OR channel does not match | 0 | (none) |

Note: sources from blocked channels (`channel_block`) are already excluded before scoring. Sources from non-allowlisted channels are already excluded when `channel_allow` is set. The channel_bonus therefore rewards known-good channels when the allow list is configured and the score is used across multiple runs or when a single channel is compared against its peers.

Open question: if `channel_allow` is configured and all included sources are from allowed channels, the channel_bonus becomes a constant +10 for everyone and adds no differentiation. Should the bonus only be awarded when the source is from the single highest-priority channel (if allow list has multiple entries)?

---

## Scoring location in pipeline

Scoring is applied **inside `apply_filters`**, after all filter steps (channel, recency, duration, views, deduplication) and before the cap (step 7). This means:

- All sources (included and excluded) receive `quality_score` and `quality_factors`.
- Sources filtered out by channel/recency/duration/views still get scores (informational; visible in sources.json).
- The cap then selects the top `selection_cap` sources by `quality_score DESC`, `view_count DESC` (view_count breaks ties).

The scoring function is a standalone helper in `sources.py`:

```python
def score_source(
    source: dict,
    *,
    channel_allow: Optional[str],
    today: date,
) -> tuple[int, list[str]]:
    """Return (quality_score, quality_factors) for a single source dict."""
```

`today` is injected as a parameter (not `date.today()` inside the function) so tests can fix the reference date without monkeypatching.

---

## Selection cap change

Current (step 7 of `apply_filters`):
```python
included.sort(key=lambda x: x.get("view_count") if x.get("view_count") is not None else -1, reverse=True)
```

New:
```python
included.sort(key=lambda x: (x.get("quality_score", 0), x.get("view_count") or 0), reverse=True)
```

No other changes to `apply_filters` interface.

---

## `apply_filters` interface change

`apply_filters` needs `today` for recency scoring. Options:

A) Add `today: Optional[date] = None` parameter; default to `date.today()` inside.
B) Compute scores in `curate_sources` instead, passing results into `apply_filters`.

Open question: which approach keeps tests cleanest and the function interface most stable?

---

## `curation_report.md` change

The included sources table gains two columns after `Published`:

```
| # | Title | Channel | Views | Duration | Published | Score | Factors | URL | Notes |
```

- `Score`: integer, e.g. `72`.
- `Factors`: quality_factors list, max 3 labels shown, comma-separated. If more than 3: show first 3 followed by `...`. If empty: `-`.

Example row:
```
| 3 | Some Tutorial | GreatChan | 87500 | 15m 10s | 2026-02-03 | 63 | high_views, recent | https://... |  |
```

The existing `_write_curation_report` function in `cli.py` must be updated. No other CLI changes.

---

## Missing/null field handling

| Field | Missing/null behavior |
|---|---|
| `view_count` | views_score = 0; no factor label |
| `published_at` | recency_score = 0; no factor label |
| `duration_seconds` | duration_score = 0; no factor label |
| `channel` | channel_bonus = 0 (cannot match allowlist) |

Missing field handling must never raise an exception. If ALL fields are missing: `quality_score=0`, `quality_factors=[]`.

---

## Acceptance criteria

1. Every source in `sources.json` has `quality_score` (int in [0, 100]) and `quality_factors` (list of strings).
2. Score is deterministic: same inputs + same `today` always produce the same output.
3. Selection cap sorts included sources by `quality_score DESC`, `view_count DESC`.
4. A source with higher quality_score is selected over a lower-score source when both would otherwise compete for the cap.
5. Tie on quality_score: higher view_count wins.
6. Channel allowlist configured: source on allowlist gets 10-point bonus vs source not on allowlist.
7. Channel allowlist not configured: channel_bonus = 0 for all sources.
8. All four null-field cases handled without exception.
9. `quality_factors` labels are exactly the strings defined in this spec (no freeform text).
10. `curation_report.md` includes `Score` and `Factors` columns for included sources.
11. Factors column shows max 3 labels; truncates with `...` when more than 3.
12. `score_source` function is importable and testable standalone (no yt-dlp dependency).

---

## Tests required (minimum 12, no network)

All tests are unit tests. No yt-dlp, no NotebookLM, no file I/O beyond what's needed.

| Test | Description |
|---|---|
| `test_score_high_views_recent_ideal` | Source with high views + fresh + ideal duration scores near max |
| `test_score_old_low_views` | Source with low views + old date scores near 0 |
| `test_score_missing_view_count` | view_count=None: no exception, views_score=0 |
| `test_score_missing_published_at` | published_at=None: no exception, recency_score=0 |
| `test_score_missing_duration` | duration_seconds=None: no exception, duration_score=0 |
| `test_score_ideal_duration` | 8-25 min source gets max duration_score; label=ideal_duration |
| `test_score_short_duration` | < 2 min source gets duration_score=0 |
| `test_score_allowlist_bonus` | channel on allow list: channel_bonus=10 in score |
| `test_score_no_allowlist` | no allow list configured: channel_bonus=0 |
| `test_cap_sorts_by_score` | Higher-score source selected over lower-score when both fit in cap |
| `test_cap_tiebreak_by_views` | Same quality_score: higher view_count wins the cap |
| `test_quality_factors_populated` | quality_factors contains expected label strings |
| `test_score_range_clamped` | quality_score always in [0, 100] |
| `test_curation_report_score_column` | curation_report.md includes Score column |
| `test_curation_report_factors_truncated` | Factors column truncates to 3 + `...` |

---

## Outputs contract

`sources.json` schema gains two fields per source entry. No other contract changes. `curation_report.md` table format changes (two new columns). Both are additive; no existing fields removed.

---

## Rollout plan

- Implement in `sources.py`: add `score_source` function, call it inside `apply_filters`, update cap sort.
- Update `cli.py`: update `_write_curation_report` to render Score and Factors columns.
- No other file changes.

---

## Decision log

- 2026-03-07 (draft): Scoring is metadata-only. No network calls. Formula is four-component weighted sum. Channel blocklist does not influence score (blocked sources are already excluded). `score_source` injectable `today` parameter for testability.

---

## Remaining open questions (blocking interview)

1. **View count breakpoints:** Are the proposed piecewise breakpoints (>=500k, >=100k, >=50k, >=10k, >=1k) appropriate for the expected YouTube search result distribution? Should they be fewer and coarser?
2. **Recency bracket labels:** Should the `<=90 days` and `<=180 days` brackets share the label `"recent"`, or should `<=90 days` get `"recent"` and `<=180 days` get nothing?
3. **Duration sweet spot:** Is 8-25 minutes the right ideal range? Should it be wider?
4. **Channel bonus differentiation problem:** When `channel_allow` is set, all included sources are from allowed channels, so the bonus does not differentiate. Should the bonus be redesigned or removed?
5. **Scoring location:** Should `score_source` be called inside `apply_filters` (requiring a `today` parameter on `apply_filters`) or called from `curate_sources` before passing to `apply_filters`?
6. **Excluded sources scored:** Should excluded sources also get `quality_score`/`quality_factors`, or only included sources?
