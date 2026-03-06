# Architecture — {{intent}} / {{query}}
Deliverables requested: {{deliverables}}

**Constraint:** Do NOT discuss strategy, hype, pros/cons, or irreversible decisions. Output only implementation details.

Summarize the architecture patterns and technical setup steps described across the sources for "{{query}}".

For each component or layer identified in the sources, provide:
- The exact setup or configuration steps (commands, file paths, config keys)
- Dependencies and version requirements
- Integration points with adjacent components

Cite the source when the detail comes from a specific video or document. Do not hallucinate URLs; use the title or channel name if no URL is available.

---

## Map to our stack (nlm-orch)

After summarizing source material, restate every external tool or wrapper mentioned using our actual toolchain:

- Any reference to a NotebookLM Python wrapper or API client maps to the `notebooklm` CLI and `nlm-orch`.
- Output paths map to our outputs contract: `outputs/<run_id>/sources.json`, `outputs/<run_id>/run_manifest.json`, `outputs/<run_id>/notes/`, `outputs/<run_id>/artifacts/`.
- Setup and verification commands in our stack: `nlm-orch doctor`, `nlm-orch login`, `nlm-orch sources "<query>"`, `nlm-orch run "<query>"`.

If a source describes a step that does not map to any of the above, note it explicitly as "not yet implemented in nlm-orch".

---

## Troubleshooting (manifest-driven)

When a run fails or produces unexpected output, check in this order:

1. `nlm-orch doctor` -- confirms yt-dlp found, notebooklm CLI found, auth state present. Exit 4 means a tool is missing. Exit 5 means auth is missing; run `nlm-orch login`.
2. `outputs/<run_id>/run.log` -- full step-by-step trace.
3. `outputs/<run_id>/run_manifest.json` -- structured diagnosis:
   - `status`: `success`, `partial`, `failed`, or `dry-run`
   - `failed_step`: which step aborted the run
   - `warnings[]`: non-fatal issues that continued the run

Common failures and what they mean:
- `status=failed`, `failed_step=preflight`, exit 4: notebooklm CLI version < 0.3.3. Fix: `pip install -U notebooklm`.
- `warnings[].type=source_add_failed`: one or more sources could not be added. Run continues; check `warnings[].urls` for the affected URLs.
- `warnings[].type=source_wait_timeout`: a source was added but indexing did not confirm in time. Usually harmless; the source may still be usable.
- `status=partial`: at least one deliverable failed to download. Check `warnings[]` for the artifact name and error.
