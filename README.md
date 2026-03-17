# NotebookLM Orchestrator

CLI pipeline that curates YouTube and web sources, pushes them into Google NotebookLM, and downloads deliverables (slide deck, infographic, briefing).

---

## New here? Start with this section

### Step 1 — Prerequisites (install once)

- Python 3.11 via Homebrew:
  ```bash
  brew install python@3.11
  ```
- yt-dlp and ffmpeg:
  ```bash
  brew install yt-dlp ffmpeg
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
pip install playwright
playwright install chromium
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

## Getting zero results? How to diagnose and fix

### Step 1 — Find your run folder

Every run writes output to `outputs/<run_id>/`. The run ID is printed at the start:

```
nlm-orch run started. run_id=startup_pitch_20260317_105132
```

```bash
ls outputs/
# startup_pitch_20260317_105132/
```

---

### Step 2 — Check what the filters removed

```bash
python3 -c "
import json
with open('outputs/<run_id>/sources.json') as f:
    d = json.load(f)
from collections import Counter
reasons = Counter(s['exclusion_reason'] for s in d['sources'] if not s['included'])
for reason, count in reasons.most_common():
    print(f'{count:3d}  {reason}')
"
```

Replace `<run_id>` with your actual folder name. Example output:

```
 38  recency
  9  min_views
  3  max_duration
```

That tells you exactly which filter removed what.

---

### Step 3 — Fix by relaxing the filters

Three filters are on by default. All three also reject videos with missing metadata (no date, no duration, no view count).

#### Filter 1: `--recency` (default: `6months`)

Rejects any video published more than 6 months ago, and any video with no upload date.

| Value | What it allows |
|---|---|
| `6months` | Last 180 days (default) |
| `1year` | Last 365 days |
| `2years` | Last 730 days |
| `all` | No date filter — include everything |

```bash
# Widen to 2 years
nlm-orch sources "startup pitch" --recency 2years

# Remove the date filter entirely
nlm-orch sources "startup pitch" --recency all
```

---

#### Filter 2: `--max-duration` (default: `30m`)

Rejects any video longer than 30 minutes, and any video with no duration metadata.

| Value | What it allows |
|---|---|
| `30m` | Up to 30 minutes (default) |
| `60m` | Up to 1 hour |
| `2h` | Up to 2 hours |
| `all` | No duration filter |

```bash
# Allow up to 1 hour
nlm-orch sources "startup pitch" --max-duration 60m

# Remove the duration filter entirely
nlm-orch sources "startup pitch" --max-duration all
```

---

#### Filter 3: `--min-views` (default: `1000`)

Rejects any video with fewer than 1000 views, and any video with no view count.

| Value | What it allows |
|---|---|
| `1000` | At least 1000 views (default) |
| `500` | At least 500 views |
| `100` | At least 100 views |
| `0` | No view filter |

```bash
# Lower the bar to 100 views
nlm-orch sources "startup pitch" --min-views 100

# Remove the view filter entirely
nlm-orch sources "startup pitch" --min-views 0
```

---

### Step 4 — Combine relaxed filters

```bash
# Typical fix for niche or older topics
nlm-orch sources "startup pitch" \
  --recency 2years \
  --max-duration 60m \
  --min-views 100

# Remove all filters — get everything yt-dlp returns
nlm-orch sources "startup pitch" \
  --recency all \
  --max-duration all \
  --min-views 0
```

---

### Step 5 — Check the raw yt-dlp output

If even `--recency all --max-duration all --min-views 0` returns 0 results, the problem is upstream of the filters — yt-dlp returned no candidates at all.

```bash
# See the raw yt-dlp log
cat outputs/<run_id>/run.log

# Count how many raw JSON objects yt-dlp returned
wc -l outputs/<run_id>/raw.jsonl
```

If `raw.jsonl` is empty or has 0 lines, yt-dlp found nothing. Try a broader or different query.

---

### Quick reference: all tunable filter flags

| Flag | Default | Unit | Disable with |
|---|---|---|---|
| `--recency` | `6months` | `Nd`, `Nmonths`, `Nyears`, or `all` | `--recency all` |
| `--max-duration` | `30m` | `Nm` (minutes) or `Nh` (hours), or `all` | `--max-duration all` |
| `--min-views` | `1000` | integer (view count) | `--min-views 0` |
| `--channel-allow` | off | comma-separated channel names | omit flag |
| `--channel-block` | off | comma-separated channel names | omit flag |

All flags work with both `nlm-orch sources` and `nlm-orch run`.

---

## Key constraints

- NotebookLM has a 50-source cap per notebook. Curation filters matter.
- NotebookLM automation uses an unofficial client. It can break if Google changes internals.
- Auth state (`~/.notebooklm/`) lives outside the repo. Do not commit it.
