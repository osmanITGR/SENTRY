#!/usr/bin/env python3
"""Build one self-contained .zip per skill for upload to claude.ai
(Settings -> Capabilities -> Skills), which makes them available in every
project and every Claude surface on the account.

Usage: python3 package_skills.py [--out DIR]   (default: <kit>/dist)

Each zip holds <skill>/SKILL.md plus its files. Skills whose scripts depend
on detect_stack.py get their own copy, because uploaded skills are not
installed side by side. Frontmatter is checked against the keys claude.ai accepts.
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
SKILLS_DIR = KIT / "skills"
SHARED = {"detect_stack.py": SKILLS_DIR / "codebase-recon" / "scripts" / "detect_stack.py"}
NEEDS_SHARED = {"verification-gate": ["detect_stack.py"], "ci-setup": ["detect_stack.py"],
                "live-modernize": ["detect_stack.py"]}
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def frontmatter_keys(text: str) -> list[str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return []
    return re.findall(r"^([A-Za-z_-]+):", m.group(1), re.M)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=KIT / "dist")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    errors = 0
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        skill = skill_md.parent
        keys = frontmatter_keys(skill_md.read_text(encoding="utf-8"))
        bad = [k for k in keys if k not in ALLOWED_KEYS]
        if "name" not in keys or "description" not in keys or bad:
            print(f"SKIP {skill.name}: frontmatter keys {keys} (not allowed: {bad})")
            errors += 1
            continue
        zpath = args.out / f"{skill.name}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(skill.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, f"{skill.name}/{f.relative_to(skill).as_posix()}")
            for name in NEEDS_SHARED.get(skill.name, []):
                z.write(SHARED[name], f"{skill.name}/scripts/{name}")
        print(f"built {zpath.name}")
    print(f"\nZips in {args.out}. Upload each one at claude.ai -> Settings -> Capabilities -> Skills.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
