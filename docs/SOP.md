# SOP: NotebookLM Orchestrator

Second brain for this repo. Read this before touching code or specs.

---

## Repo entrypoints

| Path | Purpose |
|---|---|
| `SPEC.md` | Start here. Points to the active spec index. |
| `spec/2026-03-04_000_index.md` | Lists all active specs and canonical interview order. |
| `docs/outputs_template/` | Tracked template for the `outputs/<run_id>/` contract. |

---

## Canonical workflow

**One spec at a time. Never implement before interviewing.**

```
1. interview   -- read one spec file, ask clarifying questions, surface gaps
2. plan        -- write a short implementation plan, confirm with user
3. implement   -- make changes, run verification, update docs if needed
```

Interview order (from index):
1. `spec/2026-03-04_010_core.md`
2. `spec/2026-03-04_020_cli.md`
3. `spec/2026-03-04_040_youtube.md`
4. `spec/2026-03-04_030_notebooklm.md`
5. `spec/2026-03-04_090_testing_ops.md`

---

## Phase gates

### Phase 2: complete when

- `nlm-orch --help` exits 0 and prints usage
- `nlm-orch doctor` exits 0 (requires: `yt-dlp` found, `notebooklm` CLI found, `~/.notebooklm/storage_state.json` present)

### Phase 3: next (do not implement yet)

- `nlm-orch sources` runs `yt-dlp` for real and writes `raw.jsonl` + curated `sources.json`
- `nlm-orch run` creates a NotebookLM notebook, adds sources, generates slide deck, infographic, and briefing, downloads all artifacts to `outputs/<run_id>/artifacts/`

---

## Setup (macOS)

Use Homebrew Python 3.11. Do not use `/usr/bin/python3` (see Common Failures).

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Verify:
```bash
nlm-orch --help
nlm-orch doctor
```

Auth (once per machine):
```bash
nlm-orch login
```

---

## Common failures

### macOS system Python is 3.9.6

`/usr/bin/python3` is the Xcode CLI Tools Python, pinned at 3.9.6. The project requires 3.11+.

Fix: rebuild the venv explicitly.
```bash
deactivate
rm -rf .venv
/opt/homebrew/bin/python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### zsh autocorrect rewrites `pip` or `python`

zsh may silently correct `pip install` to something else, or shadow the venv `pip` with a system one.

Fix: always call pip through the Python interpreter to guarantee you are using the venv binary.
```bash
python -m pip install ...
python -m pip list
```

### `doctor` finds tools from the wrong environment

`doctor` resolves tools in order: venv-local, then Homebrew, then PATH. `yt-dlp` is expected at `/opt/homebrew/bin/yt-dlp` (Homebrew install). `notebooklm` is expected inside `.venv/bin/` (pip install). If `doctor` reports null for either, the venv is not activated or the tool is not installed.

Fix:
```bash
source .venv/bin/activate
which notebooklm    # should be inside .venv/bin/
which yt-dlp        # should be /opt/homebrew/bin/yt-dlp or inside .venv/bin/
nlm-orch doctor
```

---

## Output cleanup

`outputs/` is gitignored and grows unbounded. To keep the last 20 runs and delete the rest:

```bash
ls -dt outputs/*/ | tail -n +21 | xargs rm -rf
```

---

## Safety: never commit these

```
outputs/             # all run artifacts
~/.notebooklm/storage_state.json
~/.notebooklm/browser_profile/
*.cookies
```

These are listed in `.gitignore`. Do not force-add them.

---

## Intent pack runs

One example per intent:

```bash
# Default: strategy overview, risks, practices taxonomy
nlm-orch run "claude code skills" --deliverables briefing

# Architecture and implementation checklist
nlm-orch run "claude code skills" --intent implementation --deliverables briefing

# Deck narrative and infographic spec
nlm-orch run "claude code skills" --intent deliverables --deliverables slides infographic
```

---

## Pack validation

Run one command per intent and verify the outputs are distinct:

```bash
nlm-orch run "Claude Code NotebookLM workflow" --deliverables briefing --intent strategy
nlm-orch run "Claude Code NotebookLM workflow" --deliverables briefing --intent implementation
```

Check `outputs/<run_id>/notes/ask_*.md`: strategy output should contain `Hard-to-reverse decisions`; implementation output should contain `Map to our stack (nlm-orch)` and `Troubleshooting (manifest-driven)`.

---

## Smoke test (known good)

```bash
nlm-orch run "claude code skills" --deliverables briefing
```

Expected outputs:
- `outputs/<run_id>/` created
- `artifacts/briefing.md` exists
- `notes/ask_0.md` exists
- `run_manifest.json` has `status=success` (or `success` with warnings for minor source failures)

Troubleshooting:
- If doctor fails: run `nlm-orch doctor`
- If auth missing: run `nlm-orch login`
- If version gate fails: upgrade with `pip install -U notebooklm` (requires >= 0.3.3)
