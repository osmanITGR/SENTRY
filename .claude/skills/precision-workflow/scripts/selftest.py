#!/usr/bin/env python3
"""Self-test for the skill suite: validates every SKILL.md and exercises the
bundled scripts against a throwaway multi-stack fixture repository.

Usage: python3 .claude/skills/precision-workflow/scripts/selftest.py
Exit 0 when every assertion holds.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
DETECT = SKILLS / "codebase-recon/scripts/detect_stack.py"
VERIFY = SKILLS / "verification-gate/scripts/verify.py"
DEAD = SKILLS / "legacy-cleanup/scripts/find_dead_code.py"
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def validate_skills() -> None:
    names = set()
    for skill_md in sorted(SKILLS.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        m = re.match(r"^---\nname: ([a-z0-9-]+)\ndescription: (.+?)\n---\n", text, re.S)
        folder = skill_md.parent.name
        check(bool(m), f"{folder}: frontmatter has name + description")
        if not m:
            continue
        check(m.group(1) == folder, f"{folder}: name matches folder")
        check(40 <= len(m.group(2)) <= 1024, f"{folder}: description length {len(m.group(2))}")
        check(len(text.splitlines()) < 500, f"{folder}: under 500 lines")
        names.add(folder)
        for ref in re.findall(r"\.claude/skills/([\w-]+/scripts/[\w.]+)", text):
            check((SKILLS / ref).exists(), f"{folder}: referenced script {ref} exists")
    for skill_md in SKILLS.glob("*/SKILL.md"):
        for ref in re.findall(r"`([a-z]+(?:-[a-z]+)+)`", skill_md.read_text(encoding="utf-8")):
            if (SKILLS / ref).is_dir():
                check(ref in names, f"{skill_md.parent.name}: cross-ref `{ref}` is a skill")


def write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def build_fixture(root: Path) -> None:
    write(root, "web/package.json", json.dumps({"name": "web", "scripts": {
        "lint": "node -e \"process.exit(0)\"", "build": "node -e \"0\"", "test": "node --test"}}))
    write(root, "web/package-lock.json", "{}")
    write(root, "web/src/util.js", "export function usedHelper(x) { return x }\n"
          "export function neverCalled(y) { return y }\n"
          "// const old = compute(1);\n// if (old) { doThing(); }\n// return old;\n"
          "/** @deprecated use usedHelper */\nexport const legacyThing = (a) => a\n")
    write(root, "web/src/index.js", "import { usedHelper } from './util.js'\nusedHelper(1)\n")
    write(root, "web/src/orphanmod.js", "export function lonely() {}\n")
    write(root, "web/test/a.test.js", "import test from 'node:test'\ntest('ok', () => {})\n")
    write(root, "api/pyproject.toml", "[project]\nname='api'\n[tool.pytest.ini_options]\n")
    write(root, "api/svc.py", "def handle_used():\n    return 1\n\ndef dead_func():\n    return 2\n")
    write(root, "api/tests/test_svc.py", "from svc import handle_used\n")
    write(root, "robot/robot.ino", "void setup() {}\nvoid loop() {}\nint readSonar(int pin) {\n  return pin;\n}\n")
    write(root, "app/pubspec.yaml", "name: app\ndependencies:\n  flutter:\n    sdk: flutter\n")
    write(root, ".github/workflows/ci.yml", "jobs:\n  t:\n    steps:\n      - run: npm test\n")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=root, check=True)


def run(script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=600)


def test_scripts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_fixture(root)

        det = json.loads(run(DETECT, ".", "--json", cwd=root).stdout)
        stacks = {p["root"]: p for p in det["projects"]}
        check(stacks.get("web", {}).get("stack") == "node", "detect: node project at web/")
        check(stacks.get("web", {}).get("commands", {}).get("install") == "npm ci",
              "detect: npm ci chosen from package-lock.json")
        check(stacks.get("api", {}).get("stack") == "python", "detect: python project at api/")
        check(stacks.get("app", {}).get("stack") == "flutter", "detect: flutter project at app/")
        check(stacks.get("robot", {}).get("stack") == "arduino", "detect: arduino sketch at robot/")
        check(any("npm test" in c for c in det["ci_commands"]), "detect: CI run commands parsed")

        v = run(VERIFY, ".", "--root", "web", cwd=root)
        check(v.returncode == 0 and "VERDICT: PASS" in v.stdout, "verify: web passes")
        v = run(VERIFY, ".", "--root", "robot", cwd=root)
        check(v.returncode == 2 and "UNVERIFIED" in v.stdout, "verify: all-skipped -> exit 2")
        write(root, "web/test/b.test.js",
              "import test from 'node:test'\nimport a from 'node:assert'\ntest('x', () => a.equal(1, 2))\n")
        v = run(VERIFY, ".", "--changed", "--only", "test", cwd=root)
        check(v.returncode == 1 and "FAIL  web:test" in v.stdout, "verify: failing test -> exit 1")
        check("api:test" not in v.stdout, "verify: --changed scopes to touched project")
        (root / "web/test/b.test.js").unlink()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                                capture_output=True, text=True).stdout
        check(status.strip() == "", f"verify: leaves no artifacts ({status.strip()!r})")

        d = run(DEAD, ".", "--no-tools", cwd=root).stdout
        for name in ("neverCalled", "legacyThing", "dead_func", "readSonar", "lonely"):
            check(f"  {name}  " in d or f"  {name}    " in d, f"dead-code: finds {name}")
        for name in ("usedHelper", "handle_used", "setup", "loop"):
            check(f"  {name}    |" not in d, f"dead-code: no false positive on {name}")
        check("web/src/orphanmod.js" in d, "dead-code: finds orphan file")
        check("@deprecated" in d, "dead-code: finds deprecated marker")
        check("web/src/util.js:3  (3 lines)" in d, "dead-code: finds commented-out block")


if __name__ == "__main__":
    validate_skills()
    test_scripts()
    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)
