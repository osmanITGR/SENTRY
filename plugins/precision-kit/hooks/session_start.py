#!/usr/bin/env python3
"""SessionStart hook: give Claude the repo's stacks and exact check commands
up front, so no session starts by guessing how to build or test."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DETECT = ROOT / "skills" / "codebase-recon" / "scripts" / "detect_stack.py"
FRESHNESS = ROOT / "skills" / "live-modernize" / "scripts" / "freshness_report.py"
CODE_MAP = ROOT / "skills" / "code-map" / "scripts" / "code_map.py"
VAULT = ROOT / "skills" / "project-vault" / "scripts" / "vault.py"
DAY = 86400


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


def freshness_line(cwd: Path) -> str | None:
    """Cached live-freshness summary; refresh in the background when older than a day.
    Never blocks session start on the network."""
    option = os.environ.get("CLAUDE_PLUGIN_OPTION_FRESHNESS_ON_START", "true").strip().lower()
    if option in ("false", "0", "no", "off"):
        return None
    fr = load(FRESHNESS, "freshness_report")
    cache_dir = Path(os.environ.get("CLAUDE_PLUGIN_DATA") or Path.home() / ".cache" / "precision-kit")
    cache = fr.cache_file(cwd, cache_dir)
    if not cache.exists() or time.time() - cache.stat().st_mtime > DAY:
        flags = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([sys.executable, str(FRESHNESS), str(cwd), "--cache-ttl", str(DAY), "--summary",
                          "--cache-dir", str(cache_dir)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **flags)
    if not cache.exists():
        return "[precision-kit freshness] live check running in background; summary appears next session."
    out = subprocess.run([sys.executable, str(FRESHNESS), str(cwd), "--summary", "--cache-only",
                          "--cache-dir", str(cache_dir)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    return out.stdout.strip() or None


def code_map_line(cwd: Path) -> str:
    """Bring the code map up to date (incremental, fast) or build it in the background."""
    cm_mod = load(CODE_MAP, "code_map")
    repo = cm_mod.find_repo(cwd)
    if not (repo / ".claude" / "code-map" / "index.json").exists():
        flags = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([sys.executable, str(CODE_MAP), "--repo", str(repo), "build"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **flags)
        return ("[precision-kit code-map] building the project map in the background. Before opening files use "
                f"`python3 {CODE_MAP} summary|find|show|refs` and read only the listed line ranges.")
    cm = cm_mod.CodeMap(repo)
    res = cm.update()
    files = cm.data["files"]
    nsym = sum(len(e["symbols"]) for e in files.values())
    stale = [f for f in cm.notes if cm.note_for(f)[1]]
    return (f"[precision-kit code-map] {len(files)} files / {nsym} symbols mapped "
            f"({len(res['changed']) + len(res['added']) + len(res['removed'])} changed since last session"
            + (f", {len(stale)} stale notes" if stale else "") + "). Don't read whole files: "
            f"`python3 {CODE_MAP} summary|find|show|refs|deps`, then ranged Reads (code-map skill).")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not (cwd / ".git").exists() and not any((p / ".git").exists() for p in cwd.parents):
        return 0  # not a repository: nothing useful to say
    det = load(DETECT, "detect_stack").detect(cwd, max_depth=2)
    lines = ["[precision-kit] For code tasks follow the precision-workflow skill."]
    for p in det["projects"][:8]:
        cmds = "; ".join(f"{k}: {v}" for k, v in p["commands"].items() if k != "install")
        missing = f" (missing: {', '.join(p['missing_tools'])})" if p["missing_tools"] else ""
        lines.append(f"- {p['root']}: {p['stack']}/{p['package_manager']}{missing} -> {cmds}")
    if len(det["projects"]) > 8:
        lines.append(f"- ... {len(det['projects']) - 8} more projects (run detect_stack.py)")
    if det["instruction_files"]:
        lines.append("Read first: " + ", ".join(det["instruction_files"]))
    try:
        lines.append(code_map_line(cwd))
    except Exception as exc:  # the map is an optimisation, never a blocker
        lines.append(f"[precision-kit code-map] skipped: {exc}")
    if det["projects"]:
        try:
            out = subprocess.run([sys.executable, str(VAULT), "status", str(cwd)], capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=60)
            if out.stdout.strip():
                lines.append(out.stdout.strip())
        except Exception as exc:  # the vault reminder must never break a session
            lines.append(f"[precision-kit vault] skipped: {exc}")
        try:
            line = freshness_line(cwd)
            if line:
                lines.append(line)
        except Exception as exc:  # freshness is advisory
            lines.append(f"[precision-kit freshness] skipped: {exc}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        sys.exit(main())
    except Exception as exc:  # a context hint must never break a session
        print(f"[precision-kit] session_start skipped: {exc}", file=sys.stderr)
        sys.exit(0)
