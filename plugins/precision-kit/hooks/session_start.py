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
                          "--cache-dir", str(cache_dir)], capture_output=True, text=True, timeout=20)
    return out.stdout.strip() or None


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
    if det["projects"]:
        try:
            line = freshness_line(cwd)
            if line:
                lines.append(line)
        except Exception as exc:  # freshness is advisory
            lines.append(f"[precision-kit freshness] skipped: {exc}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a context hint must never break a session
        print(f"[precision-kit] session_start skipped: {exc}", file=sys.stderr)
        sys.exit(0)
