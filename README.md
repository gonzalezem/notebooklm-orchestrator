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

`nlm-orch doctor` checks that `yt-dlp` and the `notebooklm` CLI are reachable and that auth state exists at `~/.notebooklm/storage_state.json`. Exits 0 only when all three pass. It also enforces notebooklm CLI version >= 0.3.3 (fails fast if older).

## NotebookLM auth

Log in once before running pipelines:

```bash
nlm-orch login
```

This opens a browser, completes Google OAuth, and writes auth state to:

- `~/.notebooklm/storage_state.json` - session cookies
- `~/.notebooklm/browser_profile/` - browser profile

**Do not copy these into the repo.** They live outside the repo under `~/.notebooklm/` and are not meant to be committed.

## Implementation status

| Subcommand | Status |
|---|---|
| `nlm-orch doctor` | Implemented |
| `nlm-orch login` | Implemented |
| `nlm-orch sources "<query>"` | Implemented (real yt-dlp curation, filtering, provenance) |
| `nlm-orch run "<query>"` | Implemented. Supports `--dry-run`; generates deliverables via NotebookLM; records warnings for non-fatal failures (e.g., some sources fail to add). |

## Quickstart

```bash
nlm-orch sources "claude code skills"
nlm-orch run "claude code skills" --dry-run
nlm-orch run "claude code skills" --deliverables briefing
```

## Prompt packs and `--intent`

Each `nlm-orch run` loads a prompt pack from `prompts/packs/<intent>/` before any `--prompts` files. Prompts are sent to NotebookLM in lexical order within the pack, then user-supplied files.

| Intent | Pack directory | Use when |
|---|---|---|
| `strategy` (default) | `prompts/packs/strategy/` | Landscape overview, risks, practices |
| `implementation` | `prompts/packs/implementation/` | Architecture decisions, checklists |
| `deliverables` | `prompts/packs/deliverables/` | Deck narrative, infographic spec |

Example:
```bash
nlm-orch run "claude code skills" --intent implementation --deliverables briefing
```

If the pack directory is missing or empty and no `--prompts` files are provided, the run exits 2.

## Outputs contract

Each run writes to `outputs/<run_id>/`:

Note: `artifacts/` is created even in `--dry-run` (empty). `notes/` is created when prompts are asked; ask responses are saved as `ask_N.md`.

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
  notes/
    ask_0.md
    ask_1.md
```

The tracked template for this structure lives at `docs/outputs_template/`.
