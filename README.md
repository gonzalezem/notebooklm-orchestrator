# NotebookLM Orchestrator

CLI-first research and deliverables pipeline.

## CLI

The main entrypoint is `nlm-orch`.

It:
1. Searches and curates sources (YouTube via `yt-dlp`, plus direct URLs and optional local files)
2. Pushes curated sources into Google NotebookLM
3. Asks analysis questions using prompt templates
4. Generates deliverables (slide deck, infographic, briefing)
5. Downloads artifacts to `outputs/<run_id>/` with an auditable `run_manifest.json`

Every run writes a manifest containing filters, the exact source list, prompts used, NotebookLM notebook id, and artifact filenames.

## Key constraints

- NotebookLM has a 50-source cap per notebook, so curation matters.
- NotebookLM automation uses an unofficial client. It can break if Google changes internals.
- By default, only public URLs are uploaded. Local file upload is opt-in.

## Install (macOS)

**Prerequisites:**
- Python 3.11 via Homebrew (`brew install python@3.11`)
- `yt-dlp` (`brew install yt-dlp`)
- Google account with NotebookLM access

**Do not use `/usr/bin/python3`** (macOS system Python is 3.9 and will cause version errors).

**Create the virtual environment:**
```bash
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Verification

```bash
nlm-orch --help
nlm-orch doctor
```

`nlm-orch doctor` checks that `yt-dlp` and the `notebooklm` CLI are reachable and that auth state exists at `~/.notebooklm/storage_state.json`. Exits 0 only when all three pass.

## NotebookLM auth

Log in once before running pipelines:

```bash
nlm-orch login
```

This opens a browser, completes Google OAuth, and writes auth state to:

- `~/.notebooklm/storage_state.json` - session cookies
- `~/.notebooklm/browser_profile/` - browser profile

**Do not commit these paths.** They are listed in `.gitignore`.

## Implementation status

| Subcommand | Status |
|---|---|
| `nlm-orch doctor` | Implemented |
| `nlm-orch login` | Implemented |
| `nlm-orch sources "<query>"` | Implemented (real yt-dlp curation, filtering, provenance) |
| `nlm-orch run "<query>"` | Stub only -- Phase 3b |

## Outputs contract

Each run writes to `outputs/<run_id>/`:

```
outputs/<run_id>/
  raw.jsonl
  sources.json
  run_manifest.json
  run.log
  artifacts/
    deck.pdf
    infographic.png
    briefing.md
```

The tracked template for this structure lives at `docs/outputs_template/`.
