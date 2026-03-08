# Spec: Deliverables Handoff Guide
Date: 2026-03-07
Status: draft (pre-interview)

---

## Problem

`nlm-orch run` downloads `deck.pdf` and `infographic.png` from NotebookLM, but leaves the user without any guidance on how to make them editable, apply branding, or share them. The next step for most users is to import the PDF into Canva or Google Slides and adapt the design. This is a predictable, recurring friction point that can be documented once and surfaced automatically.

---

## Proposed feature

When `nlm-orch run` completes and the deliverables list includes `slides` and/or `infographic`, write `outputs/<run_id>/deliverables_handoff.md`. The file is human-readable Markdown: it lists what was generated, gives step-by-step editing instructions for Canva and Google Slides, and provides a post-editing checklist.

If the deliverables list contains only `briefing`, do not write the file (briefing is already Markdown; no PDF import steps are needed).

---

## Scope

- Write side-effect only: one new Markdown file per qualifying run.
- No new CLI flags in v1.
- No third-party API calls.
- No changes to NotebookLM operations or the curation pipeline.
- Triggers on the `slides` and/or `infographic` keywords in `--deliverables`.

---

## Trigger condition

Write `deliverables_handoff.md` if and only if:

```python
any(kw in args.deliverables for kw in ("slides", "infographic"))
```

This check happens after deliverable downloads complete (step 10 in `cmd_run`), regardless of whether downloads succeeded or failed (partial runs still get the file).

Open question: should the file be written even if every visual deliverable download failed (i.e., `deck.pdf` and `infographic.png` are both absent)? If so, the file would list those paths as "not downloaded" rather than linking to actual files.

---

## Output path

```
outputs/<run_id>/deliverables_handoff.md
```

Not written in `--dry-run` or `--review` mode (no deliverables generated in those modes).

---

## File contents

The file is generated from a Python helper function `_write_handoff(run_dir, artifacts_result, query, run_id)`. All content is either static prose or derived from run-time data (paths, query, run_id). No external data fetched.

### Section 1: What was generated

Heading: `## Generated deliverables`

A bullet list of each visual deliverable that was requested, with:
- The artifact keyword and filename
- Status: `downloaded` (file exists) or `not downloaded` (failed or missing)
- Absolute path if downloaded, else `—`

Example:
```markdown
## Generated deliverables

- **slides** → `outputs/<run_id>/artifacts/deck.pdf` (downloaded)
- **infographic** → `outputs/<run_id>/artifacts/infographic.png` (downloaded)
- **briefing** → `outputs/<run_id>/artifacts/briefing.md` (downloaded)
```

If briefing was not requested: omit it. Show only the deliverables that were in `--deliverables`.

### Section 2: Make editable in Canva

Heading: `## Make editable in Canva`

Show this section only if `slides` or `infographic` was requested (always shown when the file is written).

Static prose + steps:

```markdown
## Make editable in Canva

### Slide deck (deck.pdf)

1. Go to [canva.com](https://canva.com) and click **Create a design**.
2. Choose **Import** and upload `artifacts/deck.pdf`.
3. Canva will convert each page to an editable slide. Review layout fidelity.
4. Apply your brand colors and fonts using **Brand Kit** (Canva Pro) or manually per slide.
5. Replace placeholder images if any were inserted by NotebookLM.
6. Export as **PowerPoint (.pptx)** or **PDF** when done.

### Infographic (infographic.png)

1. Go to [canva.com](https://canva.com) and click **Create a design → Custom size**.
2. Import the PNG as a background image using **Uploads → Upload files**.
3. Overlay editable text boxes and shapes on top to make content modifiable.
4. Alternatively, use **Edit photo → Background Remover** to isolate elements (Canva Pro).
5. Export as PNG (for web) or PDF (for print).
```

Open question: should URLs in the Markdown be full hyperlinks (`[canva.com](https://canva.com)`) or plain text? Full links are more useful but introduce external URLs into a generated file.

### Section 3: Make editable in Google Slides

Heading: `## Make editable in Google Slides`

Show this section only if `slides` was requested.

```markdown
## Make editable in Google Slides

1. Open [Google Drive](https://drive.google.com) and click **New → File upload**.
2. Upload `artifacts/deck.pdf`.
3. Right-click the uploaded PDF and choose **Open with → Google Slides**.
4. Google will convert the PDF to an editable presentation. Text and layout fidelity varies.
5. Apply theme colors via **Slide → Edit theme**.
6. Download as **PowerPoint (.pptx)** or share directly from Drive.
```

### Section 4: Post-editing checklist

Heading: `## Post-editing checklist`

Static content:

```markdown
## Post-editing checklist

- [ ] Apply brand colors and fonts to all slides/graphics.
- [ ] Verify citations: each claim should trace back to a source in `sources.json`.
- [ ] Review slide order and narrative flow against the original query.
- [ ] Remove or replace any NotebookLM watermarks or boilerplate footers, if permitted by your licence.
- [ ] Check image resolution before print export (infographic.png should be 300 DPI minimum for print).
- [ ] Export in the required format (pptx, pdf, png, svg) for your audience.
- [ ] Archive this run folder (`outputs/<run_id>/`) for reproducibility.
```

### Section 5: Provenance reference

Heading: `## Provenance`

Dynamic content:

```markdown
## Provenance

- **Run ID:** `<run_id>`
- **Query:** `<query>`
- **Manifest:** `outputs/<run_id>/run_manifest.json`
- **Sources:** `outputs/<run_id>/sources.json`

The manifest records all filters, prompt files used, NotebookLM notebook ID, and artifact download statuses.
```

---

## `_write_handoff` helper

New function in `cli.py` (alongside `_write_curation_report`):

```python
def _write_handoff(
    handoff_path: Path,
    deliverables: list[str],
    artifacts_result: list[dict],
    query: str,
    run_id: str,
    run_dir: Path,
) -> None:
    """Write deliverables_handoff.md. Called only when slides/infographic requested."""
```

- `deliverables`: the `args.deliverables` list (e.g. `["slides", "infographic"]`)
- `artifacts_result`: the list of artifact dicts from step 10 (each has `keyword`, `filename`, `status`, optionally `path`)
- Reads no external files. All content is generated from parameters.

---

## Outputs contract addition

When the trigger condition is met:

```
outputs/<run_id>/
  ...
  deliverables_handoff.md    # NEW
```

Not added to `docs/outputs_template/` as a permanent fixture (it is conditional).

Open question: should it be added to the tracked template as a placeholder, or left as a conditional output only documented in this spec?

---

## Manifest change

Add `handoff_path` to `run_manifest.json` when the file is written:

```json
"handoff_path": "outputs/<run_id>/deliverables_handoff.md"
```

Set to `null` when not written (briefing-only runs, dry-run, review).

Open question: is it worth adding this field to the manifest, or is the file's presence in the run folder sufficient documentation?

---

## Partial run behavior

If some visual deliverables failed to download:
- The file is still written.
- Section 1 lists each deliverable with its actual status (`downloaded` or `not downloaded`).
- Sections 2 and 3 still contain the full editing instructions (the user may re-download manually).

---

## Exit code and error handling

Writing `deliverables_handoff.md` must never affect the run exit code. If the write fails (e.g. disk full), log a warning and continue. The file is informational; a write failure is non-fatal.

---

## Acceptance criteria

1. File written when `slides` in deliverables, even if download failed.
2. File written when `infographic` in deliverables, even if download failed.
3. File written when both `slides` and `infographic` in deliverables.
4. File NOT written when `briefing` only in deliverables.
5. File NOT written in `--dry-run` mode.
6. File NOT written in `--review` mode.
7. Section 1 correctly shows `downloaded` for artifacts that exist, `not downloaded` for those that failed.
8. Google Slides section present only when `slides` in deliverables.
9. Checklist section always present when file is written.
10. Provenance section includes run_id, query, and paths to manifest and sources.
11. Write failure is non-fatal (run still exits 0 or with its normal code).

---

## Tests required (minimum 8, no network)

All tests call `_write_handoff` directly or call `cmd_run` with a mocked NLM stack.

| Test | Description |
|---|---|
| `test_handoff_written_slides_only` | deliverables=["slides"]: file written |
| `test_handoff_written_infographic_only` | deliverables=["infographic"]: file written |
| `test_handoff_written_slides_and_infographic` | deliverables=["slides","infographic"]: file written |
| `test_handoff_not_written_briefing_only` | deliverables=["briefing"]: file NOT written |
| `test_handoff_partial_slides_missing` | slides requested + download failed, infographic present: file written, slides listed as not downloaded |
| `test_handoff_section_google_slides_present` | slides in deliverables: Google Slides section present |
| `test_handoff_section_google_slides_absent` | infographic only: no Google Slides section |
| `test_handoff_checklist_present` | checklist section always present when file written |
| `test_handoff_provenance_contains_run_id` | provenance section contains run_id and query |
| `test_handoff_not_written_dry_run` | --dry-run: file NOT written |

---

## Rollout

- Single surgical addition to `cli.py`: add `_write_handoff` helper and call it in `cmd_run` after step 10.
- No changes to `sources.py`, `notebooklm_cli.py`, or `pyproject.toml`.

---

## Decision log

- 2026-03-07 (draft): Feature triggered by slides/infographic in deliverables. Briefing-only runs excluded. No new CLI flags in v1.
- 2026-03-07 (draft): Write failure is non-fatal. Partial run still gets the file.

---

## Remaining open questions (blocking interview)

1. Write when all visual downloads failed? Or skip entirely if nothing was downloaded?
2. External URLs as hyperlinks vs plain text in the generated file?
3. Google Slides section: show for `infographic` too (import PNG into Slides) or only for `slides`?
4. Add `handoff_path` to manifest, or leave it undocumented there?
5. Add to `docs/outputs_template/` as a conditional placeholder, or not?
6. Should there be a brief "Next steps" intro paragraph at the top of the file before Section 1?
