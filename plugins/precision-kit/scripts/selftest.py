#!/usr/bin/env python3
"""Self-test for precision-kit: validates every SKILL.md and the plugin
manifests, then exercises every bundled script and hook against throwaway
fixture repositories.

Usage: python3 plugins/precision-kit/scripts/selftest.py
Exit 0 when every assertion holds.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SKILLS = KIT / "skills"
DETECT = SKILLS / "codebase-recon/scripts/detect_stack.py"
VERIFY = SKILLS / "verification-gate/scripts/verify.py"
DEAD = SKILLS / "legacy-cleanup/scripts/find_dead_code.py"
SCAN = SKILLS / "secret-scan/scripts/scan_secrets.py"
GEN_CI = SKILLS / "ci-setup/scripts/gen_ci.py"
GUARD = KIT / "hooks/pre_commit_guard.py"
SESSION = KIT / "hooks/session_start.py"
PACKAGE = KIT / "scripts/package_skills.py"
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
        check(".claude/skills/" not in text, f"{folder}: no hard-coded install path")
        for ref in re.findall(r"\$\{CLAUDE_SKILL_DIR\}/(scripts/[\w.]+)", text):
            check((skill_md.parent / ref).exists(), f"{folder}: bundled {ref} exists")
    workflow = (SKILLS / "precision-workflow/SKILL.md").read_text(encoding="utf-8")
    for name in sorted(names - {"precision-workflow"}):
        check(f"`{name}`" in workflow, f"precision-workflow routes to `{name}`")
    for skill_md in SKILLS.glob("*/SKILL.md"):
        for ref in set(re.findall(r"`([a-z]+(?:-[a-z]+)+)` skill", skill_md.read_text(encoding="utf-8"))):
            check(ref in names or ref in ("security-review",),
                  f"{skill_md.parent.name}: referenced skill `{ref}` exists")
    for manifest in (KIT / ".claude-plugin/plugin.json", KIT.parents[1] / ".claude-plugin/marketplace.json",
                     KIT / "hooks/hooks.json"):
        try:
            json.loads(manifest.read_text())
            check(True, f"{manifest.name} is valid JSON")
        except (OSError, json.JSONDecodeError) as e:
            check(False, f"{manifest.name} is valid JSON ({e})")


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


def git_commit_all(root: Path) -> None:
    for args in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c"]):
        subprocess.run(["git", *args], cwd=root, check=True)


def test_secret_scan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write(root, "a.py", "x = 1\n")
        git_commit_all(root)
        write(root, "a.py", "x = 1\n"
              'password = "hunter2hunter2"\n'  # secret-scan: allow (fake fixture)
              'token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"\n'  # secret-scan: allow (fake fixture)
              'url = "postgres://admin:S3cr3tPass@db.example.com/app"\n'  # secret-scan: allow (fake fixture)
              'connect("user", "realpass123")\n'  # secret-scan: allow (fake fixture)
              'db = os.environ["DB_PASSWORD"]\n'
              'api_key = "changeme"\n'
              'k = "your-api-key-here"\n'
              'u = "postgres://user:${DB_PASS}@db/app"\n'
              'ok = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"  # secret-scan: allow\n')
        write(root, ".env", "SECRET=abc\n")
        write(root, ".env.example", "SECRET=\n")
        out = run(SCAN, str(root), cwd=root)
        check(out.returncode == 1, "secret-scan: findings -> exit 1")
        for label in ("a.py:2  hard-coded secret", "a.py:3  GitHub token", "a.py:4  credentials in URL",
                      "a.py:5  credentials passed", "SENSITIVE FILE  .env "):
            check(label in out.stdout, f"secret-scan: finds {label.split('  ')[-1].strip()}")
        for line in (6, 7, 8, 9, 10):
            check(f"a.py:{line} " not in out.stdout, f"secret-scan: no false positive on line {line}")
        check("hunter2hunter2" not in out.stdout, "secret-scan: values are masked")
        check(".env.example" not in out.stdout, "secret-scan: templates are allowed")
        out = run(SCAN, str(root), "--mode", "staged", cwd=root)
        check(out.returncode == 0, "secret-scan: --mode staged ignores unstaged changes")


def test_ci_and_packaging() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_fixture(root)
        write(root, "web/.nvmrc", "20\n")
        out = run(GEN_CI, ".", cwd=root)
        check(out.returncode == 0, "gen_ci: exit 0")
        y = out.stdout
        check("web-node:" in y and "api-python:" in y, "gen_ci: one job per project")
        check("node-version-file: web/.nvmrc" in y, "gen_ci: node version from .nvmrc")
        check("working-directory: web" in y, "gen_ci: monorepo working-directory")
        check("permissions:\n  contents: read" in y, "gen_ci: least-privilege permissions")
        check("not generated (needs manual setup): robot (arduino)" in y,
              "gen_ci: parameterised projects listed, not guessed")
        try:
            import yaml  # type: ignore
            check(isinstance(yaml.safe_load(y)["jobs"], dict), "gen_ci: valid YAML")
        except ImportError:
            check(y.count("\t") == 0, "gen_ci: no tabs in YAML (pyyaml unavailable)")
        out = run(GEN_CI, ".", "--write", cwd=root)
        check((root / ".github/workflows/ci.yml").exists() is False or out.returncode == 1,
              "gen_ci: refuses to overwrite an existing workflow")
    with tempfile.TemporaryDirectory() as tmp:
        out = run(PACKAGE, "--out", tmp, cwd=Path(tmp))
        zips = sorted(Path(tmp).glob("*.zip"))
        check(out.returncode == 0 and len(zips) == len(list(SKILLS.glob("*/SKILL.md"))),
              f"package: one zip per skill ({len(zips)})")
        with zipfile.ZipFile(Path(tmp) / "verification-gate.zip") as z:
            check("verification-gate/scripts/detect_stack.py" in z.namelist(),
                  "package: shared detect_stack.py bundled into dependent skills")


def hook(script: Path, payload: dict, cwd: Path, env: dict | None = None):
    return subprocess.run([sys.executable, str(script)], input=json.dumps(payload), cwd=cwd,
                          capture_output=True, text=True, timeout=600,
                          env={**os.environ, **(env or {})})


def test_hooks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write(root, "web/package.json", json.dumps({"name": "w", "scripts": {
            "lint": "node -e 0", "test": "node --test"}}))
        write(root, "web/test/a.test.js", "const test = require('node:test')\ntest('ok', () => {})\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        git_commit_all(root)
        bash = lambda c: {"tool_name": "Bash", "cwd": str(root), "tool_input": {"command": c}}

        out = hook(SESSION, {"cwd": str(root), "hook_event_name": "SessionStart"}, root)
        check(out.returncode == 0 and "web: node/npm" in out.stdout, "session hook: lists project commands")
        check(hook(GUARD, bash("ls"), root).returncode == 0, "guard: ignores non-commit commands")
        write(root, "web/test/a.test.js", "const test = require('node:test')\ntest('ok2', () => {})\n")
        out = hook(GUARD, bash("git commit -am x"), root)
        check(out.returncode == 0 and "VERDICT: PASS" in out.stdout, "guard: passing commit allowed + context")
        write(root, "web/test/b.test.js", "const test = require('node:test')\nconst a = require('node:assert')\n"
              "test('bad', () => a.equal(1, 2))\n")
        check(hook(GUARD, bash("git add -A && git commit -m x"), root).returncode == 2,
              "guard: failing checks block the commit")
        check(hook(GUARD, bash("PRECISION_SKIP_VERIFY=1 git commit -am x"), root).returncode == 0,
              "guard: explicit skip token honoured")
        check(hook(GUARD, bash("git commit -am x"), root,
                   {"CLAUDE_PLUGIN_OPTION_VERIFY_ON_COMMIT": "false"}).returncode == 0,
              "guard: verify_on_commit=false honoured")
        check(hook(GUARD, bash("echo 'then git commit'"), root).returncode == 0,
              "guard: quoted 'git commit' text ignored")
        (root / "web/test/b.test.js").unlink()
        write(root, "web/cfg.js", 'const t = "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB"\n')  # secret-scan: allow (fake fixture)
        out = hook(GUARD, bash("PRECISION_SKIP_VERIFY=1 git -C . commit -am x"), root)
        check(out.returncode == 2 and "secrets" in out.stderr, "guard: secrets block even with skip token")


if __name__ == "__main__":
    validate_skills()
    test_scripts()
    test_secret_scan()
    test_ci_and_packaging()
    test_hooks()
    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)
