# Claude instructions for notebooklm-orchestrator

## Current phase
We are completing Phase 2 documentation only.
Do NOT implement Phase 3 (no real yt-dlp logic, no NotebookLM operations beyond documentation).

## Repo intent
CLI-first orchestrator:
- curates sources (YouTube via yt-dlp + URLs)
- uses NotebookLM for analysis + deliverables
- downloads artifacts into `outputs/<run_id>/`
- writes an auditable `run_manifest.json`

## Non-negotiables
- Do not change the CLI command name: `nlm-orch`.
- Do not change the outputs contract.
- Do not add new top-level directories.
- Do not add new runtime outputs outside `outputs/`.
- Do not commit secrets, cookies, auth caches, browser profiles, or NotebookLM storage state.
- Do not add dependencies or change `pyproject.toml` unless explicitly instructed.

## Outputs contract (locked)
Each run writes:
outputs/<run_id>/
  sources.json
  run_manifest.json
  run.log
  artifacts/
    deck.pdf
    infographic.png
    briefing.md

Tracked template lives at: `docs/outputs_template/`.

## Specs and second brain
- Entry point: `SPEC.md`
- Active specs: `spec/2026-03-04_000_index.md` lists the current spec set.
- Specs are date-prefixed for lexical sorting.

## Phase 2 deliverable targets
1) Update `README.md` to accurately reflect Phase 2:
   - correct venv creation using Homebrew Python 3.11 path
   - how to install editable
   - how to run doctor
   - mention NotebookLM login and where auth state is stored
   - reference `docs/outputs_template/`

2) Create `docs/SOP.md` as the repo second brain:
   - canonical workflow: spec → interview → plan → implement
   - phase gates (Phase 2 done; Phase 3 next)
   - command snippets (make venv/install/doctor if Makefile exists; otherwise explicit commands)
   - “common failures” section (macOS python3=3.9 trap, PATH issues, zsh autocorrect)

## Style constraints for docs
- Be concise and procedural.
- No em dashes.
- No motivational fluff.
- Use code blocks for commands.
- Prefer exact file paths and exact command lines.

## What to output in Claude Code
- Make file edits directly.
- After changes, print a short summary:
  - files changed
  - key additions
  - any assumptions
  