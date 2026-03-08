# Spec: Curation Review Mode
Date: 2026-03-07
Status: draft (pre-interview)

---

## Problem

`nlm-orch run` proceeds directly from curation into NotebookLM without any human checkpoint. There is no way to inspect which sources were included or excluded before committing to a full pipeline run. Sources that passed the filters may still be irrelevant; sources excluded by duration or view count may be worth reinstating. Users have no structured way to review and edit the curated source set before upload.

---

## Proposed feature

Add a `--review` flag to `nlm-orch run`. When set:

1. Execute curation as normal (yt-dlp, filters, `raw.jsonl`, `sources.json`, `run_manifest.json`, `run.log`).
2. Write `outputs/<run_id>/curation_report.md` summarizing included and excluded sources.
3. Stop. Do not create a NotebookLM notebook. Do not upload sources. Do not generate deliverables.
4. Print the path to `curation_report.md` and a one-liner telling the user how to edit `sources.json` and rerun.

The user then edits `sources.json` if needed and reruns with `--sources outputs/<run_id>/sources.json` to skip curation and proceed to NotebookLM.

---

## Scope

- YouTube-mining only. No changes to NotebookLM operations.
- One new flag on `nlm-orch run`: `--review` (boolean, default off).
- One new output file: `curation_report.md`.
- No changes to `nlm-orch sources`, `nlm-orch doctor`, or `nlm-orch login`.

---

## CLI change

```
nlm-orch run "<query>" --review [all other curation flags]
```

`--review` is mutually exclusive with `--dry-run` (both stop before NotebookLM, but `--dry-run` is a pipeline gate; `--review` is a curation inspection tool). Open question: should they conflict with an error, or should `--review` silently take precedence?

---

## Outputs contract addition

When `--review` is active, the run folder contains:

```
outputs/<run_id>/
  raw.jsonl
  sources.json
  run_manifest.json
  run.log
  curation_report.md    # NEW
  artifacts/            # present but empty (existing contract)
  notes/                # present but empty (existing contract)
```

`curation_report.md` is not written on normal runs or `--dry-run` runs.

---

## `curation_report.md` format

The report is a Markdown file written by the CLI. It must contain three sections:

### Section 1: Included sources table

A Markdown table with one row per source where `included=true` in `sources.json`.

Columns:
| # | Title | Channel | Views | Duration | Published | URL | Notes |
|---|---|---|---|---|---|---|---|

- `#`: 1-based row index (matches position in `sources.json` for editing reference).
- `Duration`: formatted as `Xm Ys` (e.g., `12m 30s`).
- `Published`: `published_at` field, formatted as `YYYY-MM-DD`.
- `Notes`: empty placeholder column. Intended for the user to fill in manually before deciding to edit `sources.json`.

### Section 2: Excluded sources summary

Do not list every excluded source individually (list can be large). Instead:

- Total excluded count.
- Breakdown table by `exclusion_reason`:

| Exclusion reason | Count |
|---|---|
| too_long | N |
| too_short | N |
| too_old | N |
| low_views | N |
| blocked_channel | N |
| ... | N |

Open question: should there be an opt-in flag (`--review-verbose`) to also dump the full excluded list? Default: summary only.

### Section 3: How to edit and rerun

A fixed prose block (not generated from data) explaining:

1. Open `outputs/<run_id>/sources.json`.
2. To remove a source: set `"included": false` on that entry.
3. To reinstate an excluded source: set `"included": true` and clear `"exclusion_reason"`.
4. Rerun with: `nlm-orch run "<original query>" --sources outputs/<run_id>/sources.json [other flags]`

---

## `run_manifest.json` changes

When `--review` is set:
- `status` = `"review"` (new status value; existing values: `success`, `partial`, `failed`, `dry-run`).
- `review_report_path`: absolute path to `curation_report.md`.
- No `notebook_id`, no `artifacts`, no `prompts` fields (these are absent or null; they are never populated in review mode).

---

## Exit codes

`--review` succeeds (exit 0) if curation completes and `curation_report.md` is written.
Existing failure exits apply to the curation step (exit 3 if no sources found after curation; exit 1 for unexpected errors).

---

## Acceptance criteria

1. `nlm-orch run "<query>" --review` exits 0; `curation_report.md` written; no NotebookLM calls made.
2. `run_manifest.json` has `status="review"` and `review_report_path` set.
3. `curation_report.md` contains all three sections: included table, excluded summary by reason, rerun instructions.
4. Included table row count matches the count of `included=true` entries in `sources.json`.
5. Excluded breakdown counts sum to total number of `included=false` entries in `sources.json`.
6. `artifacts/` and `notes/` directories exist and are empty.
7. If zero sources are included (all excluded): exit 3, no `curation_report.md` written (consistent with existing no-sources behavior).
8. `--review` with `--dry-run`: open question (see CLI change section).

---

## Tests required (no network)

All tests use mocked yt-dlp / mocked `sources.json` input. No live NotebookLM or YouTube calls.

| Test | Description |
|---|---|
| `test_review_exits_0` | `--review` with valid sources exits 0 |
| `test_review_writes_report` | `curation_report.md` exists in run dir |
| `test_review_manifest_status` | manifest `status == "review"` and `review_report_path` is set |
| `test_review_no_nlm_calls` | `nl_cli.create_notebook` never called in review mode |
| `test_review_included_table_rows` | included table row count matches included sources |
| `test_review_excluded_summary_counts` | excluded breakdown sums to total excluded |
| `test_review_section3_present` | "How to edit" section present in report |
| `test_review_artifacts_and_notes_dirs_exist` | both dirs created and empty |
| `test_review_zero_sources_exits_3` | all sources excluded: exit 3, no report written |
| `test_review_duration_format` | duration rendered as `Xm Ys` not raw seconds |

---

## Open questions (blocking interview)

1. Flag name: `--review` or `--curation-review`? `--review` is shorter; `--curation-review` is self-documenting.
2. `--review` + `--dry-run` conflict: error out, or let `--review` win silently?
3. Excluded source detail: summary only (default), or add `--review-verbose` for full excluded list?
4. `curation_report.md` when `--sources` is passed (skipping yt-dlp): should `--review` be allowed, or blocked with a clear error?
5. Should the DONE line (stdout) be printed in review mode, and if so, what counters to show (no artifacts, no prompts)?

---

## Decision log

- 2026-03-07 (draft): Feature scoped to YouTube-mining only. No NotebookLM operations in review mode. New `status="review"` added to manifest contract.

---

## Remaining open questions

See "Open questions" section above. All five are blocking for implementation; to be resolved in interview.
