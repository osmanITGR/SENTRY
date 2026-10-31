#!/usr/bin/env python3
"""SessionStart hook: give Claude the repo's stacks and exact check commands
up front, so no session starts by guessing how to build or test."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DETECT = ROOT / "skills" / "codebase-recon" / "scripts" / "detect_stack.py"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = Path(payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not (cwd / ".git").exists() and not any((p / ".git").exists() for p in cwd.parents):
        return 0  # not a repository: nothing useful to say
    spec = importlib.util.spec_from_file_location("detect_stack", DETECT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    det = mod.detect(cwd, max_depth=2)
    lines = ["[precision-kit] For code tasks follow the precision-workflow skill."]
    for p in det["projects"][:8]:
        cmds = "; ".join(f"{k}: {v}" for k, v in p["commands"].items() if k != "install")
        missing = f" (missing: {', '.join(p['missing_tools'])})" if p["missing_tools"] else ""
        lines.append(f"- {p['root']}: {p['stack']}/{p['package_manager']}{missing} -> {cmds}")
    if len(det["projects"]) > 8:
        lines.append(f"- ... {len(det['projects']) - 8} more projects (run detect_stack.py)")
    if det["instruction_files"]:
        lines.append("Read first: " + ", ".join(det["instruction_files"]))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a context hint must never break a session
        print(f"[precision-kit] session_start skipped: {exc}", file=sys.stderr)
        sys.exit(0)
