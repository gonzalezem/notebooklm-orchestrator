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


def cmd_run(args: argparse.Namespace) -> int:
    if not args.query and not args.sources:
        print("error: <query> is required unless --sources is provided.", file=sys.stderr)
        return 2

    outputs_dir = Path(args.outputs_dir).resolve()
    outputs_dir.mkdir(parents=True, exist_ok=True)

    run_id = args.run_id or _make_run_id(args.query)
    run_dir = _ensure_run_dir(outputs_dir, run_id)

    raw_path = run_dir / "raw.jsonl"
    sources_path = run_dir / "sources.json"
    log_path = run_dir / "run.log"

    _write_text(log_path, "Phase 2 stub: run command executed.\n")
    _write_text(raw_path, "")  # placeholder; Phase 3 writes real yt-dlp metadata

    if args.sources:
        # Copy or reference the supplied sources.json
        import shutil as _shutil
        _shutil.copy2(args.sources, sources_path)
    else:
        sources_doc = {
            "query": args.query,
            "note": "Phase 2 stub. Phase 3 will populate real curated sources via yt-dlp.",
            "sources": [],
        }
        sources_path.write_text(json.dumps(sources_doc, indent=2), encoding="utf-8")

    filters = {
        "max_results": args.max_results,
        "recency": args.recency,
        "max_duration": args.max_duration,
        "min_views": args.min_views,
        "channel_allow": args.channel_allow,
        "channel_block": args.channel_block,
    }
    now = datetime.now().isoformat(timespec="seconds")
    manifest = {
        "run_id": run_id,
        "command": "run",
        "query": args.query,
        "config_path": args.config,
        "filters": filters,
        "sources_path": args.sources,
        "notebook_id": args.notebook_id,
        "prompts": args.prompts or [],
        "deliverables": args.deliverables,
        "dry_run": args.dry_run,
        "started_at": now,
        "finished_at": now,
        "status": "dry-run" if args.dry_run else "stub",
        "artifacts": [],
        "error_summary": None,
        "note": "Phase 2 stub. Phase 3 will implement yt-dlp curation and NotebookLM operations.",
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(str(run_dir))
    return 0


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
