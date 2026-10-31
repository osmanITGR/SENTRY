#!/usr/bin/env python3
"""PostToolUse(Edit|Write|MultiEdit) hook: keep the code map current and
remind Claude when the edited file's project-summary note no longer matches
its structure. Silent when the repo has no code map or nothing is stale."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

CODE_MAP = Path(__file__).resolve().parent.parent / "skills" / "code-map" / "scripts" / "code_map.py"


def main() -> int:
    payload = json.load(sys.stdin)
    path = (payload.get("tool_input") or {}).get("file_path")
    if not path:
        return 0
    spec = importlib.util.spec_from_file_location("code_map", CODE_MAP)
    cm_mod = importlib.util.module_from_spec(spec)
    sys.modules["code_map"] = cm_mod
    spec.loader.exec_module(cm_mod)
    repo = cm_mod.find_repo(Path(path).resolve().parent)
    if not (repo / ".claude" / "code-map" / "index.json").exists():
        return 0
    cm = cm_mod.CodeMap(repo)
    cm.update()
    try:
        rel = str(Path(path).resolve().relative_to(repo)).replace("\\", "/")
    except ValueError:
        return 0
    text, stale = cm.note_for(rel)
    if stale:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"code-map: the summary note for {rel} is now stale (its symbols/imports "
                                 f"changed). Current note: \"{text}\". After finishing this file, update it: "
                                 f"code_map.py note {rel} \"<one-line purpose>\" (code-map skill)."}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never break an edit over the map
        print(f"[precision-kit] code-map hook skipped: {exc}", file=sys.stderr)
        sys.exit(0)
