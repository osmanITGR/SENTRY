#!/usr/bin/env python3
"""Install the precision-kit skills without the plugin system (Windows, macOS, Linux).

Usage:
  python3 install.py                      # personal: ~/.claude/skills (every project on this machine)
  python3 install.py --project PATH       # one project: PATH/.claude/skills (commit it to share)
  python3 install.py --uninstall [--project PATH]
  options: --force (overwrite skills with the same name), --dry-run

Hooks (session-start context, pre-commit guard) need the plugin install:
  /plugin install precision-kit --marketplace osmanITGR/precision-kit
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
SKILLS = sorted(p.parent for p in (KIT / "skills").glob("*/SKILL.md"))
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", type=Path, help="install into PATH/.claude/skills")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    target = (args.project.resolve() if args.project else Path.home()) / ".claude" / "skills"

    if args.uninstall:
        for skill in SKILLS:
            dest = target / skill.name
            if dest.exists():
                print(f"remove {dest}")
                if not args.dry_run:
                    shutil.rmtree(dest)
        return 0

    clashes = [s.name for s in SKILLS if (target / s.name).exists()]
    if clashes and not args.force:
        print(f"Already present in {target}: {', '.join(clashes)}\n"
              "Re-run with --force to overwrite them (other skills are untouched).")
        return 1
    for skill in SKILLS:
        dest = target / skill.name
        print(f"install {skill.name} -> {dest}")
        if not args.dry_run:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(skill, dest, ignore=IGNORE)
    print(f"\n{len(SKILLS)} skills installed. Start a new Claude Code session to load them.")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
