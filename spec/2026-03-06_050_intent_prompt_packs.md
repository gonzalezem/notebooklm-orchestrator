# Intent-based Prompt Packs for nlm-orch run
Date: 2026-03-06
Status: v1 (post-interview 2026-03-06)
Owner: Emmanuel Gonzalez

---

## Goals
1. Add `--intent {strategy,implementation,deliverables}` to `nlm-orch run`.
2. Each intent maps to a prompt pack directory (`prompts/packs/<intent>/`).
3. Pack prompts are loaded in lexicographic order and prepended before any user-supplied `--prompts` files.
4. Placeholder substitution (`{{query}}`, `{{intent}}`, `{{deliverables}}`) applied before sending each prompt.
5. Full provenance recorded in `run_manifest.json`.

## Non-goals
- Auto-classification of intent from sources or query.
- Changes to source curation or deliverable generation behavior.
- Short aliases for intent values.
- New NotebookLM features or MCP integrations.
- Per-intent default deliverable selection.

---

## CLI interface

### New flag
```
nlm-orch run "<query>" --intent {strategy,implementation,deliverables}
```

- Accepted values: `strategy`, `implementation`, `deliverables` (exact strings, no aliases).
- Default: `strategy` (effective even when flag not passed; recorded in manifest).
- `argparse` default is `"strategy"`.

### Interaction with `--prompts`
- Pack prompts always come first (lex order within the pack directory).
- User-supplied `--prompts` files are appended after pack prompts, in CLI order.
- Both sources contribute to `prompts_used[]` in the manifest.

### Examples
```bash
nlm-orch run "claude code" --intent strategy
nlm-orch run "claude code" --intent implementation --prompts my_extra.md
nlm-orch run "claude code"                          # defaults to strategy
```

---

## Pack directory layout

```
prompts/
  packs/
    strategy/
      00_overview.md
      01_practices_taxonomy.md
      02_risks_and_failure_modes.md
    implementation/
      00_architecture.md
      01_checklist.md
    deliverables/
      00_deck_story.md
      01_infographic_spec.md
```

- File discovery: all `*.md` and `*.txt` files in `prompts/packs/<intent>/`, sorted lexicographically.
- Prefix files with `00_`, `01_`, etc. for stable ordering.
- `prompts/analysis.md` is moved into `prompts/packs/strategy/` as `00_overview.md` (content preserved, path updated).

---

## Prompt loading logic (locked)

```
effective_intent = args.intent  # always set (default="strategy")
pack_dir = Path("prompts/packs") / effective_intent
pack_files = sorted(glob(pack_dir, "*.md") + glob(pack_dir, "*.txt"))

if pack_dir missing or pack_files is empty:
    if args.prompts:
        warn to log + manifest warnings[]; pack_files = []
    else:
        exit 2 with message: "Pack directory prompts/packs/<intent>/ is missing or empty
                               and no --prompts files were provided."

prompt_file_list = pack_files + (args.prompts or [])

if not prompt_file_list:
    exit 2 with message: "No prompts to ask. Provide --intent or --prompts."
```

Each file is read, rendered (placeholder substitution), and sent as one `ask` call.

---

## Placeholder substitution

Applied to every prompt's text before sending to NotebookLM:

| Placeholder | Replaced with |
|---|---|
| `{{query}}` | The run query string |
| `{{intent}}` | The effective intent value |
| `{{deliverables}}` | Comma-separated list of requested deliverables (e.g., `briefing, slides`) |

Unknown placeholders (any `{{other}}` not in the above table) are left unchanged. No warning emitted for unknown placeholders in v1.

Implementation: simple `str.replace` for each known placeholder.

---

## Failure modes

| Condition | Exit | Status | Action |
|---|---|---|---|
| Unknown `--intent` value | 2 | — | argparse rejects before cmd_run |
| Pack dir missing or empty, no `--prompts` | 2 | `failed` | Clear message naming expected path |
| Pack dir missing or empty, `--prompts` provided | 0/warn | warning | Log warning, continue with user files only |
| Prompt file read failure | 1 | `partial` | `failed_step="prompts_load"`, `error_summary` set |
| All prompt asks fail | 0 | warning | Recorded in `warnings[]` as before; not partial |

---

## Manifest provenance

### `inputs` block additions
```json
{
  "inputs": {
    "deliverables": ["briefing"],
    "intent": "strategy",
    "prompts_pack_dir": "prompts/packs/strategy",
    "prompts_pack_files": ["prompts/packs/strategy/00_overview.md"],
    "prompts_user_files": []
  }
}
```

`inputs.prompts_pack_files` and `inputs.prompts_user_files` are the raw (pre-render) file paths, in load order.

### `prompts_used[]` (existing, extended)
Each entry already has `file`, `text` (exact rendered text sent), `response_file`. No change to schema needed.

---

## Prompt pack skeleton content (v1)

Minimal content. Use placeholders where useful. All files must exist for CI and live tests.

**`prompts/packs/strategy/00_overview.md`**
(absorbs `prompts/analysis.md` — preserve existing content exactly, move do not copy):
```
Provide a structured overview of the main themes, key findings, and actionable insights from these sources on {{query}}.

Include:
- Main topics covered across the sources
- Points of consensus and notable disagreements
- Gaps or underexplored areas
- 3-5 concrete takeaways a practitioner can act on immediately
```

**`prompts/packs/strategy/01_practices_taxonomy.md`**
```
For the topic "{{query}}", categorize the practices and frameworks mentioned across the sources.

Group them by maturity (emerging, established, deprecated) and note any contradictions between sources.
```

**`prompts/packs/strategy/02_risks_and_failure_modes.md`**
```
Based on the sources about "{{query}}", what are the most commonly cited risks, pitfalls, and failure modes?

List them in order of frequency of mention, and note any mitigations recommended.
```

**`prompts/packs/implementation/00_architecture.md`**
```
Summarize the architecture patterns and technical setup steps described across sources for "{{query}}".

Focus on decisions that are hard to reverse once made.
```

**`prompts/packs/implementation/01_checklist.md`**
```
Create an implementation checklist for "{{query}}" based on the sources.

Format as ordered steps. Flag any steps where sources disagree on approach.
```

**`prompts/packs/deliverables/00_deck_story.md`**
```
Based on the sources about "{{query}}", outline a 5-7 slide narrative arc for a slide deck.

For each slide: title, one-sentence message, supporting evidence from the sources.
```

**`prompts/packs/deliverables/01_infographic_spec.md`**
```
Design an infographic structure for "{{query}}" using the source material.

Specify: headline, 3-5 data points or comparisons worth visualizing, and a recommended layout type (timeline, comparison table, flow diagram, etc.).
```

---

## Code changes required

### `src/notebooklm_orchestrator/cli.py`
1. Add `--intent` to the `run` subparser:
   ```python
   sp.add_argument("--intent", default="strategy",
                   choices=["strategy", "implementation", "deliverables"],
                   help="Prompt pack to use (default: strategy)")
   ```
2. Replace the current prompt-loading block (step 6) with:
   - `_load_pack_prompts(intent, pack_base)` helper: returns sorted list of file paths or raises on missing/empty.
   - `_render_prompt(text, query, intent, deliverables)` helper: applies placeholder substitution.
   - Logic per the "Prompt loading logic" section above.
3. Update `mstate["inputs"]` to include `intent`, `prompts_pack_dir`, `prompts_pack_files`, `prompts_user_files`.
4. Apply `_render_prompt` to each prompt's text before the `ask` call.
5. Remove fallback to `prompts/analysis.md` (replaced by strategy pack default).

### `prompts/`
- Create pack directories and skeleton files above.
- Delete `prompts/analysis.md` (content moved to `prompts/packs/strategy/00_overview.md`).

### `spec/2026-03-04_020_cli.md`
- Add `--intent` flag row to the `run` flags table.

---

## Testing plan

All tests mock NLM calls. No network.

Unit tests (new file `tests/test_intent_packs.py`):
1. `_load_pack_prompts` returns files in lex order.
2. `_load_pack_prompts` raises / returns empty correctly for missing dir.
3. `_load_pack_prompts` raises / returns empty correctly for empty dir.
4. `_render_prompt` substitutes `{{query}}`, `{{intent}}`, `{{deliverables}}`.
5. `_render_prompt` leaves unknown placeholders unchanged.
6. Missing pack dir + no `--prompts` → `cmd_run` exits 2.
7. Missing pack dir + `--prompts` provided → warning in manifest, run continues.
8. Pack prompts prepended before `--prompts` files in `prompts_used[]` order.
9. `inputs.intent`, `inputs.prompts_pack_dir`, `inputs.prompts_pack_files`, `inputs.prompts_user_files` all in manifest.
10. Default intent (`"strategy"`) recorded in manifest even when `--intent` not passed.

---

## Rollout

1. Create pack directories and prompt files.
2. Move `prompts/analysis.md` content into `prompts/packs/strategy/00_overview.md` (delete original).
3. Implement `_load_pack_prompts`, `_render_prompt`, update `cmd_run` step 6, update parser.
4. Update `mstate["inputs"]` block.
5. Add tests in `tests/test_intent_packs.py`.
6. Update `spec/2026-03-04_020_cli.md` with `--intent` flag.
7. Update `README.md` and `docs/SOP.md` (minimal: one line + one example each).

---

## Decision log
- 2026-03-06 (interview): Default intent = `"strategy"`. No --intent = strategy pack, same as --intent strategy.
- 2026-03-06 (interview): Ordering = pack prompts first (lex), then --prompts files appended.
- 2026-03-06 (interview): `prompts/analysis.md` moved into strategy pack as `00_overview.md`. Original deleted.
- 2026-03-06 (interview): Missing/empty pack + --prompts provided = warn + continue (not exit 2).
- 2026-03-06 (interview): Missing/empty pack + no --prompts = exit 2 (nothing to ask).
- 2026-03-06 (interview): Placeholders: `{{query}}`, `{{intent}}`, `{{deliverables}}`. Unknown placeholders left unchanged.
- 2026-03-06 (interview): No short aliases for intent values. Full names only.

---

## Remaining open questions
- None blocking v1 implementation.
