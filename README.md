# NotebookLM Orchestrator

CLI pipeline that curates YouTube and web sources, pushes them into Google NotebookLM, and downloads deliverables (slide deck, infographic, briefing).

---

## New here? Start with this section

### Step 1 — Prerequisites (install once)

- Python 3.11 via Homebrew:
  ```bash
  brew install python@3.11
  ```
- yt-dlp:
  ```bash
  brew install yt-dlp
  ```
- A Google account with NotebookLM access at [notebooklm.google.com](https://notebooklm.google.com)

> **Do not use `/usr/bin/python3`** — macOS ships Python 3.9 which will cause version errors.

---

### Step 2 — Get the repo

Open a terminal, then:

```bash
cd ~/Desktop                  # or wherever you keep projects
git clone https://github.com/gonzalezem/notebooklm-orchestrator.git
cd notebooklm-orchestrator
```

---

### Step 3 — Create the virtual environment (run once per machine)

A virtual environment is an isolated folder (`.venv/`) that holds this project's Python and packages separately from the rest of your machine. This prevents version conflicts with other Python projects. When you activate it, `nlm-orch` becomes available. When you open a new terminal, you need to activate it again.

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
pip install notebooklm-py
```

Your prompt will change to show `(.venv)` when the environment is active.

---

### Step 4 — Verify the install

```bash
nlm-orch --help
nlm-orch doctor
```

`doctor` checks that `yt-dlp` and the `notebooklm` CLI are reachable and that auth state exists. If it passes, you are ready.

---

### Step 5 — Log in to NotebookLM (run once)

```bash
nlm-orch login
```

This opens a browser, completes Google OAuth, and writes auth state to `~/.notebooklm/`. You only need to do this once (until the session expires).

---

## Every time you open a new terminal

**You must activate the virtual environment before using `nlm-orch`:**

```bash
cd /path/to/notebooklm-orchestrator
source .venv/bin/activate
```

If you skip this, you will see `zsh: command not found: nlm-orch`.

---

## Quickstart

```bash
# Curate sources only (no NotebookLM)
nlm-orch sources "claude code skills"

# Dry run (curate + create notebook, no deliverables)
nlm-orch run "claude code skills" --dry-run

# Full run, briefing only
nlm-orch run "claude code skills" --deliverables briefing
```

---

## Golden path (recommended workflow)

**1. Review sources before sending to NotebookLM:**
```bash
nlm-orch run "claude code notebooklm workflow" --review
```
Stops after curation. Writes `outputs/<run_id>/curation_report.md`. Edit `sources.json` if needed.

**2. Run the full pipeline with reviewed sources:**
```bash
nlm-orch run "claude code notebooklm workflow" \
  --sources outputs/<run_id>/sources.json \
  --deliverables slides infographic briefing \
  --intent strategy
```
Downloads `deck.pdf`, `infographic.png`, `briefing.md`, and writes `deliverables_handoff.md`.

**3. Open the handoff doc:**
```bash
open outputs/<run_id>/deliverables_handoff.md
```
Step-by-step instructions for importing into Canva or Google Slides.

---

## Subcommand reference

| Subcommand | What it does |
|---|---|
| `nlm-orch doctor` | Checks dependencies and auth state |
| `nlm-orch login` | Opens browser for Google OAuth |
| `nlm-orch sources "<query>"` | Curates sources via yt-dlp, no NotebookLM |
| `nlm-orch run "<query>"` | Full pipeline: curate, push to NLM, generate deliverables |

---

## Prompt packs and `--intent`

Each run loads a prompt pack from `prompts/packs/<intent>/` before any `--prompts` files.

| Intent | Use when |
|---|---|
| `strategy` (default) | Landscape overview, risks, practices |
| `implementation` | Architecture decisions, checklists |
| `deliverables` | Deck narrative, infographic spec |

```bash
nlm-orch run "claude code skills" --intent implementation --deliverables briefing
```

---

## Outputs

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
  notes/
    ask_0.md
    ask_1.md
```

`artifacts/` is created even in `--dry-run` (empty). The tracked template lives at `docs/outputs_template/`.

---

## Key constraints

- NotebookLM has a 50-source cap per notebook. Curation filters matter.
- NotebookLM automation uses an unofficial client. It can break if Google changes internals.
- Auth state (`~/.notebooklm/`) lives outside the repo. Do not commit it.
