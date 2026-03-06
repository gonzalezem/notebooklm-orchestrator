"""Unit tests for intent-based prompt pack loading and rendering."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

import notebooklm_orchestrator.notebooklm_cli as nl_cli
from notebooklm_orchestrator.cli import _load_pack_prompts, _render_prompt, cmd_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("notebooklm_orchestrator.cli.time.sleep", lambda s: None)


def _make_pack(pack_base: Path, intent: str, files: dict[str, str]) -> Path:
    """Create a pack dir under pack_base/intent/ with given {filename: content} pairs."""
    d = pack_base / intent
    d.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return d


def _args(tmp_path: Path, **overrides) -> argparse.Namespace:
    defaults: dict[str, Any] = dict(
        query="test query",
        sources=None,
        notebook_id=None,
        prompts=None,
        deliverables=["briefing"],
        intent="strategy",
        dry_run=False,
        max_results=5,
        recency="6months",
        max_duration="30m",
        min_views=1000,
        channel_allow=None,
        channel_block=None,
        run_id="pack_test_run",
        outputs_dir=str(tmp_path / "outputs"),
        config=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


_NB_PATH = "/fake/notebooklm"
_NB_ID = "nb-pack-0001"
_TASK_ID = "task-pack-0001"
_SRC_ID = "src-pack-0001"


def _fake_sources_json(tmp_path: Path) -> Path:
    sources = [{"type": "youtube", "video_id": "v0",
                "url": "https://www.youtube.com/watch?v=v0",
                "title": "Vid 0", "channel": "C", "view_count": 1000,
                "duration_seconds": 300, "published_at": "2026-01-01",
                "included": True, "exclusion_reason": None}]
    p = tmp_path / "sources.json"
    p.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return p


def _mock_nlm(monkeypatch, tmp_path: Path):
    """Patch all notebooklm_cli calls for a successful run."""
    (tmp_path / "storage_state.json").touch()
    monkeypatch.setattr(nl_cli, "which_notebooklm", lambda: _NB_PATH)
    monkeypatch.setattr(nl_cli, "auth_state_path", lambda: tmp_path / "storage_state.json")
    monkeypatch.setattr(nl_cli, "get_version", lambda *a: "0.3.3")
    monkeypatch.setattr(nl_cli, "create_notebook", lambda *a, **k: _NB_ID)
    monkeypatch.setattr(nl_cli, "use_notebook", lambda *a, **k: None)
    monkeypatch.setattr(nl_cli, "add_source",
                        lambda *a, **k: {"ok": True, "source_id": _SRC_ID, "error": None})
    monkeypatch.setattr(nl_cli, "wait_source", lambda *a, **k: True)
    monkeypatch.setattr(nl_cli, "ask", lambda *a, **k: "mock answer")
    monkeypatch.setattr(nl_cli, "generate_artifact", lambda *a, **k: _TASK_ID)
    monkeypatch.setattr(nl_cli, "wait_artifact", lambda *a, **k: True)

    def _fake_dl(nb_path, dl_type, dest, notebook_id, log_path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("content", encoding="utf-8")
        return True

    monkeypatch.setattr(nl_cli, "download_artifact", _fake_dl)


# ---------------------------------------------------------------------------
# 1. _load_pack_prompts: returns lex-sorted files
# ---------------------------------------------------------------------------

def test_load_pack_prompts_lex_order(tmp_path):
    _make_pack(tmp_path, "strategy", {
        "02_c.md": "c", "00_a.md": "a", "01_b.txt": "b",
    })
    result = _load_pack_prompts("strategy", tmp_path)
    names = [Path(p).name for p in result]
    assert names == ["00_a.md", "01_b.txt", "02_c.md"]


# ---------------------------------------------------------------------------
# 2. _load_pack_prompts: missing dir returns empty list
# ---------------------------------------------------------------------------

def test_load_pack_prompts_missing_dir(tmp_path):
    result = _load_pack_prompts("strategy", tmp_path / "nonexistent")
    assert result == []


# ---------------------------------------------------------------------------
# 3. _load_pack_prompts: empty dir returns empty list
# ---------------------------------------------------------------------------

def test_load_pack_prompts_empty_dir(tmp_path):
    (tmp_path / "strategy").mkdir()
    result = _load_pack_prompts("strategy", tmp_path)
    assert result == []


# ---------------------------------------------------------------------------
# 4. _render_prompt: substitutes query, intent, deliverables
# ---------------------------------------------------------------------------

def test_render_prompt_substitutions():
    text = "topic={{query}} mode={{intent}} out={{deliverables}}"
    result = _render_prompt(text, "my query", "strategy", ["briefing", "slides"])
    assert result == "topic=my query mode=strategy out=briefing, slides"


# ---------------------------------------------------------------------------
# 5. _render_prompt: unknown placeholders left unchanged
# ---------------------------------------------------------------------------

def test_render_prompt_unknown_placeholder_unchanged():
    text = "known={{query}} unknown={{run_id}}"
    result = _render_prompt(text, "q", "strategy", ["briefing"])
    assert "{{run_id}}" in result
    assert "{{query}}" not in result


# ---------------------------------------------------------------------------
# 6. cmd_run: pack prompts prepended before --prompts user files
# ---------------------------------------------------------------------------

def test_pack_prompts_prepended_before_user_prompts(tmp_path, monkeypatch):
    pack_base = tmp_path / "packs"
    _make_pack(pack_base, "strategy", {"00_first.md": "pack prompt"})
    user_file = tmp_path / "user.md"
    user_file.write_text("user prompt", encoding="utf-8")

    monkeypatch.setattr("notebooklm_orchestrator.cli.Path",
                        _patch_pack_base(pack_base))

    src = _fake_sources_json(tmp_path)
    args = _args(tmp_path, sources=str(src), prompts=[str(user_file)],
                 intent="strategy")
    _mock_nlm(monkeypatch, tmp_path)

    asked = []
    monkeypatch.setattr(nl_cli, "ask", lambda nb, text, nid, log: asked.append(text) or "answer")

    rc = cmd_run(args)
    assert rc == 0
    assert len(asked) == 2
    assert "pack prompt" in asked[0]
    assert "user prompt" in asked[1]


def _patch_pack_base(pack_base: Path):
    """Return a Path subclass that redirects 'prompts/packs' to pack_base."""
    import notebooklm_orchestrator.cli as cli_mod
    original_Path = cli_mod.Path

    class PatchedPath(type(original_Path())):
        def __new__(cls, *args):
            if args and str(args[0]) == "prompts/packs":
                return original_Path.__new__(original_Path, str(pack_base))
            return original_Path.__new__(original_Path, *args)

    return PatchedPath


# ---------------------------------------------------------------------------
# 7. cmd_run: missing pack + no --prompts -> exit 2
# ---------------------------------------------------------------------------

def test_missing_pack_no_user_prompts_exits_2(tmp_path, monkeypatch):
    src = _fake_sources_json(tmp_path)
    args = _args(tmp_path, sources=str(src), intent="strategy")
    _mock_nlm(monkeypatch, tmp_path)
    # Point pack_base at a dir that has no strategy subdir
    empty_base = tmp_path / "empty_packs"
    empty_base.mkdir()
    monkeypatch.setattr("notebooklm_orchestrator.cli._load_pack_prompts",
                        lambda intent, pack_base: [])

    rc = cmd_run(args)
    assert rc == 2

    manifest = json.loads(
        (tmp_path / "outputs" / "pack_test_run" / "run_manifest.json").read_text()
    )
    assert manifest["status"] == "failed"
    assert manifest["failed_step"] == "prompts_load"


# ---------------------------------------------------------------------------
# 8. cmd_run: missing pack + --prompts provided -> warning, continues
# ---------------------------------------------------------------------------

def test_missing_pack_with_user_prompts_warns_and_continues(tmp_path, monkeypatch):
    src = _fake_sources_json(tmp_path)
    user_file = tmp_path / "fallback.md"
    user_file.write_text("fallback prompt", encoding="utf-8")
    args = _args(tmp_path, sources=str(src), intent="strategy",
                 prompts=[str(user_file)])
    _mock_nlm(monkeypatch, tmp_path)
    monkeypatch.setattr("notebooklm_orchestrator.cli._load_pack_prompts",
                        lambda intent, pack_base: [])

    rc = cmd_run(args)
    assert rc == 0

    manifest = json.loads(
        (tmp_path / "outputs" / "pack_test_run" / "run_manifest.json").read_text()
    )
    assert manifest["status"] == "success"
    assert any(w["type"] == "pack_missing_or_empty" for w in manifest["warnings"])


# ---------------------------------------------------------------------------
# 9. cmd_run: manifest includes intent provenance fields
# ---------------------------------------------------------------------------

def test_manifest_includes_intent_provenance(tmp_path, monkeypatch):
    src = _fake_sources_json(tmp_path)
    args = _args(tmp_path, sources=str(src), intent="implementation")
    _mock_nlm(monkeypatch, tmp_path)

    pack_files = [str(tmp_path / "packs" / "implementation" / "00_arch.md")]
    monkeypatch.setattr("notebooklm_orchestrator.cli._load_pack_prompts",
                        lambda intent, pack_base: pack_files if intent == "implementation" else [])
    (tmp_path / "packs" / "implementation").mkdir(parents=True, exist_ok=True)
    Path(pack_files[0]).write_text("arch prompt {{query}}", encoding="utf-8")

    rc = cmd_run(args)
    assert rc == 0

    manifest = json.loads(
        (tmp_path / "outputs" / "pack_test_run" / "run_manifest.json").read_text()
    )
    assert manifest["inputs"]["intent"] == "implementation"
    assert manifest["inputs"]["prompts_pack_files"] == pack_files
    assert manifest["inputs"]["prompts_user_files"] == []
    assert "prompts/packs/implementation" in manifest["inputs"]["prompts_pack_dir"]


# ---------------------------------------------------------------------------
# 10. cmd_run: default intent (strategy) recorded even when flag not passed
# ---------------------------------------------------------------------------

def test_default_intent_recorded_in_manifest(tmp_path, monkeypatch):
    src = _fake_sources_json(tmp_path)
    args = _args(tmp_path, sources=str(src))  # no explicit intent
    assert args.intent == "strategy"
    _mock_nlm(monkeypatch, tmp_path)
    monkeypatch.setattr("notebooklm_orchestrator.cli._load_pack_prompts",
                        lambda intent, pack_base: [])
    user_file = tmp_path / "p.md"
    user_file.write_text("prompt", encoding="utf-8")
    args.prompts = [str(user_file)]

    rc = cmd_run(args)
    assert rc == 0

    manifest = json.loads(
        (tmp_path / "outputs" / "pack_test_run" / "run_manifest.json").read_text()
    )
    assert manifest["inputs"]["intent"] == "strategy"
