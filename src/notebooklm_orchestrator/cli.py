from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import __version__


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _slugify(s: str, max_len: int = 40) -> str:
    s = s.strip().lower()
    out = []
    for ch in s:
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    slug = slug.strip("_")
    return slug[:max_len] if len(slug) > max_len else slug


def _make_run_id(query: Optional[str]) -> str:
    slug = _slugify(query) if query else "run"
    return f"{slug}_{_now_ts()}"


def _ensure_run_dir(outputs_dir: Path, run_id: str) -> Path:
    run_dir = outputs_dir / run_id
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _which(cmd: str) -> Optional[str]:
    """
    Resolve an executable deterministically.

    1) Prefer venv-local executables under sys.prefix/bin.
    2) Prefer common Homebrew locations.
    3) Fall back to PATH lookup.
    """
    local = Path(sys.prefix) / "bin" / cmd
    if local.exists() and os.access(local, os.X_OK):
        return str(local)

    candidates: list[str] = []
    if cmd == "yt-dlp":
        candidates = ["/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp"]
    elif cmd == "notebooklm":
        candidates = ["/opt/homebrew/bin/notebooklm", "/usr/local/bin/notebooklm"]

    for c in candidates:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c

    return shutil.which(cmd)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> int:
    auth_state = Path.home() / ".notebooklm" / "storage_state.json"
    info = {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "yt_dlp": _which("yt-dlp"),
        "notebooklm_cli": _which("notebooklm"),
        "auth_state": str(auth_state) if auth_state.exists() else None,
    }

    print(json.dumps(info, indent=2))

    if info["yt_dlp"] is None:
        print("\nDoctor: missing yt-dlp. Install with: brew install yt-dlp", file=sys.stderr)
        return 4
    if info["notebooklm_cli"] is None:
        print("\nDoctor: notebooklm CLI not found. Install notebooklm-py in this venv.", file=sys.stderr)
        return 4
    if info["auth_state"] is None:
        print("\nDoctor: auth state not found at ~/.notebooklm/storage_state.json. Run: nlm-orch login", file=sys.stderr)
        return 5

    return 0


def cmd_login(args: argparse.Namespace) -> int:
    nb = _which("notebooklm")
    if nb is None:
        print("notebooklm CLI not found. Install notebooklm-py in this venv first.", file=sys.stderr)
        return 4
    try:
        subprocess.run([nb, "login"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 5
    auth_state = Path.home() / ".notebooklm" / "storage_state.json"
    if auth_state.exists():
        print(f"Auth state written to: {auth_state}")
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    from .sources import curate_sources

    ytdlp_path = _which("yt-dlp")
    if ytdlp_path is None:
        print("yt-dlp not found. Install with: brew install yt-dlp", file=sys.stderr)
        return 4

    outputs_dir = Path(args.outputs_dir).resolve()
    outputs_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or _make_run_id(args.query)
    run_dir = _ensure_run_dir(outputs_dir, run_id)

    raw_path = run_dir / "raw.jsonl"
    sources_path = run_dir / "sources.json"
    manifest_path = run_dir / "run_manifest.json"
    log_path = run_dir / "run.log"

    _write_text(log_path, f"nlm-orch sources started. run_id={run_id}\n")

    result = curate_sources(
        ytdlp_path=ytdlp_path,
        query=args.query,
        max_results=args.max_results,
        recency=args.recency,
        max_duration=args.max_duration,
        min_views=args.min_views,
        channel_allow=args.channel_allow,
        channel_block=args.channel_block,
        raw_path=raw_path,
        sources_path=sources_path,
        log_path=log_path,
    )

    filters = {
        "max_results": args.max_results,
        "recency": args.recency,
        "max_duration": args.max_duration,
        "min_views": args.min_views,
        "channel_allow": args.channel_allow,
        "channel_block": args.channel_block,
    }
    manifest = {
        "run_id": run_id,
        "command": "sources",
        "query": args.query,
        "config_path": args.config,
        "filters": filters,
        "yt_dlp_version": result["yt_dlp_version"],
        "yt_dlp_command": result["yt_dlp_command"],
        "candidate_count": result["candidate_count"],
        "included_count": result["included_count"],
        "excluded_count": result["excluded_count"],
        "started_at": result["started_at"],
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "status": result["status"],
        "error_summary": result.get("error_summary"),
        "outputs": {
            "raw_jsonl": str(raw_path),
            "sources_json": str(sources_path),
            "run_log": str(log_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(str(run_dir))
    return result["exit_code"]


def cmd_run(args: argparse.Namespace) -> int:  # noqa: C901
    from . import notebooklm_cli as nl_cli
    from .sources import curate_sources, SELECTION_CAP

    # ------------------------------------------------------------------
    # 1. Input validation
    # ------------------------------------------------------------------
    if not args.query and not args.sources:
        print("error: <query> is required unless --sources is provided.", file=sys.stderr)
        return 2

    # ------------------------------------------------------------------
    # 2. Create run dir early so partial manifests can always be written
    # ------------------------------------------------------------------
    outputs_dir = Path(args.outputs_dir).resolve()
    outputs_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or _make_run_id(args.query)
    run_dir = _ensure_run_dir(outputs_dir, run_id)
    notes_dir = run_dir / "notes"
    notes_dir.mkdir(exist_ok=True)

    raw_path = run_dir / "raw.jsonl"
    sources_path = run_dir / "sources.json"
    manifest_path = run_dir / "run_manifest.json"
    log_path = run_dir / "run.log"
    artifacts_dir = run_dir / "artifacts"

    started_at = datetime.now().isoformat(timespec="seconds")
    _write_text(log_path, f"nlm-orch run started. run_id={run_id}\n")

    filters = {
        "max_results": args.max_results,
        "recency": args.recency,
        "max_duration": args.max_duration,
        "min_views": args.min_views,
        "channel_allow": args.channel_allow,
        "channel_block": args.channel_block,
    }

    # Manifest accumulator — written on every exit path
    mstate: dict = {
        "run_id": run_id,
        "command": "run",
        "query": args.query,
        "config_path": args.config,
        "filters": filters,
        "dry_run": args.dry_run,
        "deliverables_requested": args.deliverables,
        "started_at": started_at,
        "finished_at": started_at,
        "status": "partial",
        "failed_step": None,
        "error_summary": None,
        "notebooklm_version": None,
        "notebook_id": args.notebook_id,
        "notebook_name": None,
        "candidate_count": 0,
        "included_count": 0,
        "excluded_count": 0,
        "sources_attempted": 0,
        "sources_add_ok": 0,
        "sources_add_failed": 0,
        "sources_failed_urls": [],
        "prompts_used": [],
        "artifacts": [],
        "missing_artifacts": [],
        "warnings": [],
        "outputs": {
            "raw_jsonl": str(raw_path),
            "sources_json": str(sources_path),
            "run_log": str(log_path),
        },
    }

    def _save_manifest(status: str, *, failed_step: Optional[str] = None,
                       error_summary: Optional[str] = None) -> None:
        mstate["status"] = status
        mstate["failed_step"] = failed_step
        mstate["error_summary"] = error_summary
        mstate["finished_at"] = datetime.now().isoformat(timespec="seconds")
        manifest_path.write_text(json.dumps(mstate, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # 3. notebooklm preflight (skip for dry-run: no NLM calls will happen)
    # ------------------------------------------------------------------
    if not args.dry_run:
        nb_path = nl_cli.which_notebooklm()
        if nb_path is None:
            msg = "notebooklm CLI not found. Install notebooklm-py in this venv."
            print(msg, file=sys.stderr)
            _save_manifest("failed", failed_step="preflight", error_summary=msg)
            return 4

        auth = nl_cli.auth_state_path()
        if not auth.exists():
            msg = f"Auth state not found at {auth}. Run: nlm-orch login"
            print(msg, file=sys.stderr)
            _save_manifest("failed", failed_step="auth", error_summary=msg)
            return 5

        mstate["notebooklm_version"] = nl_cli.get_version(nb_path, log_path)
    else:
        nb_path = None  # not used in dry-run

    # ------------------------------------------------------------------
    # 4. Source acquisition
    # ------------------------------------------------------------------
    if args.sources:
        # Use provided sources.json; copy for provenance
        import shutil as _shutil
        _shutil.copy2(args.sources, sources_path)
        raw_path.touch()
        _write_text(log_path, f"Using provided sources: {args.sources}\n")
    else:
        # Run real yt-dlp curation
        ytdlp_path = _which("yt-dlp")
        if ytdlp_path is None:
            msg = "yt-dlp not found. Install with: brew install yt-dlp"
            print(msg, file=sys.stderr)
            _save_manifest("failed", failed_step="sources", error_summary=msg)
            return 4

        src_result = curate_sources(
            ytdlp_path=ytdlp_path,
            query=args.query,
            max_results=args.max_results,
            recency=args.recency,
            max_duration=args.max_duration,
            min_views=args.min_views,
            channel_allow=args.channel_allow,
            channel_block=args.channel_block,
            raw_path=raw_path,
            sources_path=sources_path,
            log_path=log_path,
        )
        mstate["candidate_count"] = src_result["candidate_count"]
        mstate["included_count"] = src_result["included_count"]
        mstate["excluded_count"] = src_result["excluded_count"]

        if src_result["exit_code"] == 1:
            _save_manifest("failed", failed_step="sources",
                           error_summary=src_result.get("error_summary"))
            return 1
        if src_result["included_count"] == 0:
            _save_manifest("partial", failed_step="sources",
                           error_summary=src_result.get("error_summary"))
            return 3

    # Read included sources from sources.json
    included_sources = _load_included_sources(sources_path)
    if not args.sources:
        pass  # counts already set above
    else:
        all_srcs = _load_all_sources(sources_path)
        mstate["candidate_count"] = len(all_srcs)
        mstate["included_count"] = len(included_sources)
        mstate["excluded_count"] = len(all_srcs) - len(included_sources)

    if not included_sources and not args.dry_run:
        msg = "No included sources in sources.json."
        _save_manifest("partial", failed_step="sources", error_summary=msg)
        print(msg, file=sys.stderr)
        return 3

    # ------------------------------------------------------------------
    # 5. Dry-run exit: sources done, no NLM calls
    # ------------------------------------------------------------------
    if args.dry_run:
        _save_manifest("dry-run")
        print(str(run_dir))
        return 0

    # ------------------------------------------------------------------
    # 6. Load and snapshot prompts
    # ------------------------------------------------------------------
    prompt_files = args.prompts or []
    if not prompt_files:
        default_prompt_path = Path("prompts/analysis.md")
        if default_prompt_path.exists():
            prompt_files = [str(default_prompt_path)]
        else:
            prompt_files = []

    prompts_snapshot: list[dict] = []
    for pf in prompt_files:
        try:
            text = Path(pf).read_text(encoding="utf-8").strip()
            prompts_snapshot.append({"file": pf, "text": text})
        except OSError as exc:
            _write_text(log_path, f"Warning: could not read prompt file {pf}: {exc}\n")

    # ------------------------------------------------------------------
    # 7. Create or reuse notebook
    # ------------------------------------------------------------------
    try:
        if args.notebook_id:
            notebook_id = args.notebook_id
            notebook_name = None
            nl_cli.use_notebook(nb_path, notebook_id, log_path)
            _write_text(log_path, f"Reusing notebook: {notebook_id}\n")
        else:
            notebook_name = run_id  # human-readable slug+timestamp
            notebook_id = nl_cli.create_notebook(nb_path, notebook_name, log_path)
            nl_cli.use_notebook(nb_path, notebook_id, log_path)
            _write_text(log_path, f"Created notebook: {notebook_id} ({notebook_name})\n")
    except RuntimeError as exc:
        msg = str(exc)
        _save_manifest("failed", failed_step="notebook", error_summary=msg)
        print(f"Notebook error: {msg}", file=sys.stderr)
        return 1

    mstate["notebook_id"] = notebook_id
    mstate["notebook_name"] = notebook_name

    # ------------------------------------------------------------------
    # 8. Add sources (continue on partial failure)
    # ------------------------------------------------------------------
    urls = [s["url"] for s in included_sources if s.get("url")]
    urls = urls[:nl_cli.NL_MAX_SOURCES]
    add_ok, add_failed, failed_urls = 0, 0, []

    for url in urls:
        result = nl_cli.add_source(nb_path, url, notebook_id, log_path)
        if result["ok"]:
            add_ok += 1
            # Wait for source to process before adding next
            if result["source_id"]:
                nl_cli.wait_source(nb_path, result["source_id"], notebook_id, log_path)
        else:
            add_failed += 1
            failed_urls.append(url)
            _write_text(log_path, f"Source add failed for {url}: {result['error']}\n")

    mstate["sources_attempted"] = len(urls)
    mstate["sources_add_ok"] = add_ok
    mstate["sources_add_failed"] = add_failed
    mstate["sources_failed_urls"] = failed_urls

    if add_ok == 0 and urls:
        msg = "All source additions failed."
        _save_manifest("partial", failed_step="add_sources", error_summary=msg)
        print(msg, file=sys.stderr)
        return 1

    # Source add failures are non-fatal warnings (not partial) if at least 1 succeeded
    if add_failed > 0:
        mstate["warnings"].append({
            "type": "source_add_failed",
            "count": add_failed,
            "urls": failed_urls,
        })

    any_partial = False  # only set True by deliverable failures below

    # ------------------------------------------------------------------
    # 9. Ask prompts
    # ------------------------------------------------------------------
    for n, prompt in enumerate(prompts_snapshot):
        response_file = notes_dir / f"ask_{n}.md"
        try:
            answer = nl_cli.ask(nb_path, prompt["text"], notebook_id, log_path)
            response_file.write_text(answer, encoding="utf-8")
            prompt["response_file"] = str(response_file)
            _write_text(log_path, f"Prompt {n} answered. Saved to {response_file}\n")
        except RuntimeError as exc:
            _write_text(log_path, f"Warning: prompt {n} failed: {exc}\n")
            prompt["response_file"] = None
            mstate["warnings"].append({"type": "prompt_failed", "prompt_index": n})

    mstate["prompts_used"] = prompts_snapshot

    # ------------------------------------------------------------------
    # 10. Generate and download deliverables
    # ------------------------------------------------------------------
    artifacts_result: list[dict] = []
    missing_artifacts: list[str] = []

    for keyword in args.deliverables:
        if keyword not in nl_cli.DELIVERABLE_MAP:
            _write_text(log_path, f"Warning: unknown deliverable '{keyword}', skipping.\n")
            continue

        gen_type, dl_type, filename = nl_cli.DELIVERABLE_MAP[keyword]
        dest = artifacts_dir / filename
        artifact_entry: dict = {"keyword": keyword, "filename": filename, "status": "pending"}

        # Generate
        try:
            task_id = nl_cli.generate_artifact(nb_path, gen_type, notebook_id, log_path)
        except RuntimeError as exc:
            _write_text(log_path, f"Generate {keyword} failed: {exc}\n")
            artifact_entry["status"] = "generate_failed"
            artifact_entry["error"] = str(exc)
            artifacts_result.append(artifact_entry)
            missing_artifacts.append(filename)
            any_partial = True
            continue

        # Wait for generation
        if not nl_cli.wait_artifact(nb_path, task_id, notebook_id, log_path):
            _write_text(log_path, f"Artifact wait timed out for {keyword}.\n")
            artifact_entry["status"] = "wait_timeout"
            artifacts_result.append(artifact_entry)
            missing_artifacts.append(filename)
            any_partial = True
            continue

        # Download
        if nl_cli.download_artifact(nb_path, dl_type, dest, notebook_id, log_path):
            artifact_entry["status"] = "downloaded"
            artifact_entry["path"] = str(dest)
            _write_text(log_path, f"Downloaded {keyword} -> {dest}\n")
        else:
            _write_text(log_path, f"Download failed for {keyword}.\n")
            artifact_entry["status"] = "download_failed"
            missing_artifacts.append(filename)
            any_partial = True

        artifacts_result.append(artifact_entry)

    mstate["artifacts"] = artifacts_result
    mstate["missing_artifacts"] = missing_artifacts

    # ------------------------------------------------------------------
    # 11. Write final manifest
    # ------------------------------------------------------------------
    final_status = "partial" if any_partial else "success"
    _save_manifest(final_status)

    downloaded = [a for a in artifacts_result if a["status"] == "downloaded"]
    print(
        f"{run_dir}  "
        f"[notebook={notebook_id[:8]}... "
        f"sources={add_ok}/{len(urls)} "
        f"artifacts={len(downloaded)}/{len(args.deliverables)}]"
    )
    return 0


# ---------------------------------------------------------------------------
# Helpers for sources.json loading
# ---------------------------------------------------------------------------

def _load_all_sources(sources_path: Path) -> list[dict]:
    try:
        data = json.loads(sources_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "sources" in data:
        return data["sources"]
    return []


def _load_included_sources(sources_path: Path) -> list[dict]:
    return [s for s in _load_all_sources(sources_path) if s.get("included", True)]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _add_curation_flags(sp: argparse.ArgumentParser) -> None:
    """Shared curation flags for sources and run."""
    sp.add_argument(
        "--max-results", type=int, default=50, metavar="INT",
        help="Max YouTube results to fetch before curation (default: 50, cap: 50)",
    )
    sp.add_argument(
        "--recency", default="6months", metavar="WINDOW",
        help="Recency window: Nd, Nmonths, Nyears, all (default: 6months)",
    )
    sp.add_argument(
        "--max-duration", default="30m", metavar="DURATION",
        help="Max video duration: Nm or Nh (default: 30m)",
    )
    sp.add_argument(
        "--min-views", type=int, default=1000, metavar="INT",
        help="Minimum view count (default: 1000)",
    )
    sp.add_argument(
        "--channel-allow", default=None, metavar="LIST",
        help="Comma-separated channel allowlist",
    )
    sp.add_argument(
        "--channel-block", default=None, metavar="LIST",
        help="Comma-separated channel blocklist",
    )
    sp.add_argument(
        "--run-id", default=None, metavar="TEXT",
        help="Override auto-generated run ID",
    )
    sp.add_argument(
        "--outputs-dir", default="outputs", metavar="PATH",
        help="Root outputs directory (default: outputs)",
    )
    sp.add_argument(
        "--config", default=None, metavar="PATH",
        help="Config file (YAML/TOML). Wins over all flags.",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nlm-orch",
        description="NotebookLM Orchestrator -- CLI-first research and deliverables pipeline.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = p.add_subparsers(dest="cmd", required=True)

    # doctor
    sp = sub.add_parser("doctor", help="Check environment and required tool paths")
    sp.set_defaults(func=cmd_doctor)

    # login
    sp = sub.add_parser("login", help="Authenticate NotebookLM (delegates to notebooklm login)")
    sp.set_defaults(func=cmd_login)

    # sources
    sp = sub.add_parser(
        "sources",
        help="Curate YouTube sources and write sources.json",
        description="Collect YouTube candidates via yt-dlp, apply curation filters, write raw.jsonl and sources.json.",
    )
    sp.add_argument("query", help="Search query")
    _add_curation_flags(sp)
    sp.set_defaults(func=cmd_sources)

    # run
    sp = sub.add_parser(
        "run",
        help="Full pipeline: curate, create notebook, generate deliverables, download artifacts",
        description=(
            "End-to-end pipeline. Curates sources (or accepts --sources), creates a NotebookLM notebook, "
            "uploads sources, runs prompts, generates deliverables, downloads artifacts."
        ),
    )
    sp.add_argument(
        "query", nargs="?", default=None,
        help="Search query (required unless --sources is provided)",
    )
    _add_curation_flags(sp)
    sp.add_argument(
        "--sources", default=None, metavar="PATH",
        help="Use a pre-existing sources.json instead of running curation",
    )
    sp.add_argument(
        "--notebook-id", default=None, metavar="TEXT",
        help="Reuse an existing NotebookLM notebook by ID (default: create new notebook each run)",
    )
    sp.add_argument(
        "--prompts", action="append", default=None, metavar="PATH",
        help="Prompt file (.txt or .md). Repeatable. Sent to NotebookLM in order.",
    )
    sp.add_argument(
        "--deliverables", nargs="+", default=["slides", "infographic", "briefing"],
        metavar="ITEM",
        help="Deliverables to generate: slides infographic briefing (default: all three)",
    )
    sp.add_argument(
        "--dry-run", action="store_true",
        help="Stop after curation. Write manifest with status=dry-run. Do not touch NotebookLM.",
    )
    sp.set_defaults(func=cmd_run)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
