#!/usr/bin/env python3
"""Self-test for precision-kit: validates every SKILL.md and the plugin
manifests, then exercises every bundled script and hook against throwaway
fixture repositories.

Usage: python3 plugins/precision-kit/scripts/selftest.py
Exit 0 when every assertion holds.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
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
FRESH = SKILLS / "live-modernize/scripts/freshness_report.py"
DEPREC = SKILLS / "live-modernize/scripts/find_deprecations.py"
CODE_MAP = SKILLS / "code-map/scripts/code_map.py"
POST_EDIT = KIT / "hooks/post_edit_map.py"
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


def iso_days_ago(n: int) -> str:
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=n)).isoformat()


def test_live_modernize() -> None:
    """Offline: registries are replaced by a fixture; osv.dev is 'unreachable' on purpose."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write(root, "web/package.json", json.dumps({"name": "w", "dependencies": {
            "lodash": "4.17.15", "request": "^2.88.0", "react": "^18.2.0", "left-pad": "1.3.0",
            "fresh-lib": "1.0.0", "private-lib": "1.0.0"}}))
        write(root, ".nvmrc", "18\n")
        write(root, "api/requirements.txt", "django==4.2.0\n")
        write(root, "svc/go.mod", "module x\n\ngo 1.21\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.0\n"
              "\tgolang.org/x/text v0.3.0 // indirect\n)\n")
        write(root, "rs/Cargo.toml", '[package]\nname="r"\nversion="0.1.0"\n[dependencies]\nserde = "1.0.100"\n')
        npm = lambda latest, dep=None: {"dist-tags": {"latest": latest},
                                        "versions": {latest: ({"deprecated": dep} if dep else {})}}
        search = lambda name, ver, days: {"objects": [{"package": {"name": name, "version": ver,
                                                                   "date": iso_days_ago(days)}}]}
        fx = {
            "https://registry.npmjs.org/lodash": npm("4.18.1"),
            "https://registry.npmjs.org/-/v1/search?text=lodash&size=5": search("lodash", "4.18.1", 200),
            "https://registry.npmjs.org/request": npm("2.88.2", "request has been deprecated"),
            "https://registry.npmjs.org/react": npm("19.3.1"),
            "https://registry.npmjs.org/-/v1/search?text=react&size=5": search("react", "19.3.1", 30),
            "https://registry.npmjs.org/left-pad": npm("1.3.0"),
            "https://registry.npmjs.org/fresh-lib": npm("1.1.0"),
            "https://registry.npmjs.org/-/v1/search?text=fresh-lib&size=5": search("fresh-lib", "1.1.0", 2),
            "POST https://registry.npmjs.org/-/npm/v1/security/advisories/bulk": {
                "lodash": [{"severity": "high", "title": "Prototype Pollution", "url": "https://x/GHSA-1"}]},
            "https://pypi.org/pypi/django/json": {"info": {"version": "6.1.2", "classifiers": []}, "releases": {
                "4.2.0": [{"upload_time_iso_8601": iso_days_ago(900), "yanked": False}],
                "6.1.2": [{"upload_time_iso_8601": iso_days_ago(24), "yanked": False}],
                "7.0rc1": [{"upload_time_iso_8601": iso_days_ago(1), "yanked": False}]}},
            "https://pypi.org/pypi/django/4.2.0/json": {"vulnerabilities": [{"id": "PYSEC-1", "fixed_in": ["4.2.1"]}]},
            "https://proxy.golang.org/github.com/gin-gonic/gin/@latest": {"Version": "v1.12.0", "Time": iso_days_ago(244)},
            "https://nodejs.org/dist/index.json": [{"version": "v27.0.0", "lts": False},
                                                   {"version": "v26.13.0", "lts": "Krypton"}],
            "https://proxy.golang.org/golang.org/toolchain/@v/list":
                "v0.0.1-go1.27.3.linux-amd64\nv0.0.1-go1.28rc1.linux-amd64\n",
        }
        fixture = root / "fixture.json"
        fixture.write_text(json.dumps(fx))
        env = {**os.environ, "PRECISION_KIT_HTTP_FIXTURE": str(fixture), "CLAUDE_PLUGIN_DATA": str(root / "data")}
        rep = subprocess.run([sys.executable, str(FRESH), str(root), "--cache-dir", str(root / "c")],
                             capture_output=True, text=True, env=env, timeout=120)
        o = rep.stdout
        sect = lambda title: o.split("## " + title, 1)[1].split("\n##", 1)[0] if "## " + title in o else ""
        sec = sect("SECURITY")
        check(rep.returncode == 1, "freshness: security/deprecated -> exit 1")
        check("lodash 4.17.15" in sec and "Prototype Pollution" in sec, "freshness: npm advisory fallback finds lodash")
        check("django 4.2.0" in sec and "PYSEC-1" in sec, "freshness: PyPI advisory fallback finds django")
        check("django 4.2.0 -> 6.1.2" in o, "freshness: pre-releases never offered as latest")
        check("request has been deprecated" in o, "freshness: npm deprecation reported")
        check("node 18 -> 26.13.0" in o, "freshness: node compared with current LTS, not 'Current'")
        check("go 1.21 -> 1.27.3" in o and "svc/go.mod" in o, "freshness: go toolchain per project, rc ignored")
        check("react 18.2.0 -> 19.3.1" in sect("MAJOR"), "freshness: major classified")
        check("gin v1.9.0 -> v1.12.0" in sect("MINOR"), "freshness: minor classified")
        check("fresh-lib 1.0.0 -> 1.1.0" in sect("WAIT"), "freshness: cooldown WAIT for 2-day-old release")
        unknown = sect("UNKNOWN")
        check("private-lib" in unknown and "serde" in unknown, "freshness: unreachable sources listed as UNKNOWN")
        check("golang.org/x/text" not in o, "freshness: indirect go deps skipped")
        check("osv.dev" in o and "unavailable" in o, "freshness: advisory source status reported honestly")
        check("left-pad" not in o, "freshness: up-to-date deps not listed")
        summ = subprocess.run([sys.executable, str(FRESH), str(root), "--summary", "--cache-dir", str(root / "c"),
                               "--cache-ttl", "600"], capture_output=True, text=True, env=env).stdout
        check(re.search(r"2 security, 1 deprecated, 2 runtime", summ) is not None, f"freshness: summary line ({summ.strip()[:90]})")

        hook_env = {k: v for k, v in env.items()}
        first = subprocess.run([sys.executable, str(SESSION)], input=json.dumps({"cwd": str(root)}),
                               capture_output=True, text=True, env=hook_env, timeout=60)
        check("running in background" in first.stdout, "session hook: first run refreshes in background")
        deadline = time.time() + 60
        while time.time() < deadline and not list((root / "data").glob("freshness-*.json")):
            time.sleep(0.5)
        second = subprocess.run([sys.executable, str(SESSION)], input=json.dumps({"cwd": str(root)}),
                                capture_output=True, text=True, env=hook_env, timeout=60)
        check("2 security" in second.stdout, "session hook: next session shows cached freshness summary")

    if sys.version_info >= (3, 12):  # datetime.utcnow() is deprecated from 3.12
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            write(root, "pyproject.toml", "[project]\nname='p'\n")
            write(root, "legacy.py", "import datetime\n\ndef stamp():\n    return datetime.datetime.utcnow()\n")
            write(root, "tests/__init__.py", "")
            write(root, "tests/test_legacy.py", "import unittest\nfrom legacy import stamp\n\n"
                  "class T(unittest.TestCase):\n    def test_stamp(self):\n        self.assertIsNotNone(stamp())\n")
            out = run(DEPREC, str(root), cwd=root)
            check(out.returncode == 1 and "legacy.py:4" in out.stdout and "utcnow" in out.stdout,
                  "deprecations: finds deprecated API at file:line with replacement hint")


def test_code_map() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        write(root, "web/src/net/client.ts", "// HTTP client for the command API.\n"
              "import { retry } from '../util/retry'\n\n"
              "export class Client {\n  constructor(private base: string) {}\n\n"
              "  async send(cmd: { op: string }): Promise<void> {\n    await retry(() => fetch(this.base))\n  }\n"
              "  ping() { return true }\n}\n\nexport const makeClient = (url: string) => new Client(url)\n")
        write(root, "web/src/util/retry.ts", "/** Retry with backoff. */\nexport async function retry<T>(fn: () => Promise<T>): Promise<T> {\n"
              "  for (;;) {\n    try { return await fn() } catch (e) { /* again */ }\n  }\n}\n")
        write(root, "web/src/ui/Hud.tsx", "import { makeClient } from '../net/client'\n\n"
              "export function Hud({ url }: { url: string }) {\n  const c = makeClient(url)\n  return null\n}\n")
        write(root, "api/svc.py", '"""Scan service."""\nfrom store import save\n\n\nclass Scan:\n    @staticmethod\n'
              '    def validate(p):\n        return bool(p)\n\n    def handle(self, p):\n        return save(p)\n')
        write(root, "api/store.py", "def save(p):\n    return p\n")
        write(root, "svc/go.mod", "module example.com/svc\n\ngo 1.22\n")
        write(root, "svc/main.go", "package main\n\nimport (\n\t\"example.com/svc/store\"\n)\n\n"
              "func main() {\n\tstore.New().Count()\n}\n")
        write(root, "svc/store/store.go", "package store\n\ntype Store struct {\n\titems []string\n}\n\n"
              "func New() *Store { return &Store{} }\n\nfunc (s *Store) Count() int {\n\treturn len(s.items)\n}\n")
        write(root, "dist/bundle.min.js", "x")
        git_commit_all(root)
        cm = lambda *a: subprocess.run([sys.executable, str(CODE_MAP), "--repo", str(root), *a],
                                       capture_output=True, text=True, timeout=120)

        b = cm("build")
        check(b.returncode == 0 and "added" in b.stdout, "code-map: build")
        show = cm("show", "web/src/net/client.ts").stdout
        check("4-11" in show and "Client " in show, "code-map: class range 4-11")
        check(re.search(r"7-9\s+method\s+Client\.send", show) is not None, "code-map: method with inline-type param 7-9")
        check(re.search(r"10-10\s+method\s+Client\.ping", show) is not None, "code-map: one-line method")
        check("imports: web/src/util/retry.ts" in show and "imported by (1): web/src/ui/Hud.tsx" in show,
              "code-map: import graph both directions")
        check("purpose: HTTP client for the command API." in show, "code-map: purpose from leading comment")
        hud = cm("show", "web/src/ui/Hud.tsx").stdout
        check(re.search(r"3-6\s+function\s+Hud", hud) is not None, "code-map: destructured params don't end block early")
        py = cm("show", "api/svc.py").stdout
        check(re.search(r"6-8\s+method\s+Scan\.validate", py) is not None, "code-map: python range includes decorator")
        go = cm("show", "svc/store/store.go").stdout
        check(re.search(r"9-11\s+method\s+Store\.Count", go) is not None, "code-map: go receiver method qualified")
        check("svc/main.go" in cm("deps", "svc/store/store.go").stdout, "code-map: go module import resolved")
        check("dist/bundle.min.js" not in cm("summary").stdout, "code-map: build output / minified files skipped")
        f = cm("find", "send").stdout.splitlines()
        check(bool(f) and f[0].startswith("web/src/net/client.ts:7-9"), "code-map: find returns exact range first")
        r = cm("refs", "makeClient").stdout
        check("in Hud:3-6" in r and "DEF in makeClient" in r, "code-map: refs show enclosing symbol and definition")
        d = cm("deps", "web/src/util/retry.ts", "--depth", "2").stdout
        check("web/src/net/client.ts" in d and "web/src/ui/Hud.tsx" in d, "code-map: transitive reverse deps")
        gi = (root / ".claude/code-map/.gitignore").read_text()
        check("index.json" in gi and "MAP.md" in gi and "notes" not in gi.split("\n", 1)[1],
              "code-map: generated files gitignored, notes committed")

        cm("note", "web/src/net/client.ts", "Command API client")
        cm("note", "web/src/", "Frontend")
        check("Command API client" in cm("summary").stdout and "## web/src/ - Frontend" in cm("summary").stdout,
              "code-map: notes appear in summary")
        p = root / "web/src/net/client.ts"
        p.write_text(p.read_text().replace("return true", "return false"))
        out = cm("stale")
        check("1 changed" in out.stderr and "all notes current" in out.stdout,
              "code-map: body edit re-indexes 1 file, note stays current")
        p.write_text(p.read_text() + "\nexport function extra() {}\n")
        hook_out = subprocess.run([sys.executable, str(POST_EDIT)], input=json.dumps(
            {"tool_name": "Edit", "tool_input": {"file_path": str(p)}}), capture_output=True, text=True).stdout
        check("stale" in hook_out and "web/src/net/client.ts" in hook_out, "post-edit hook: stale note reminder")
        check("STALE   web/src/net/client.ts" in cm("stale").stdout, "code-map: shape change marks note stale")
        (root / "api/store.py").unlink()
        write(root, "api/new_mod.py", "def fresh():\n    pass\n")
        out = cm("find", "fresh")
        check("1 added" in out.stderr and "1 removed" in out.stderr and "api/new_mod.py:1-2" in out.stdout,
              "code-map: deleted and untracked files tracked incrementally")
        out = cm("find", "fresh")
        check(out.stderr == "", "code-map: no-change query does no re-indexing")

    with tempfile.TemporaryDirectory() as tmp:  # speed on a few hundred files
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        body = "".join(f"def f{i}(x):\n    return x + {i}\n\n" for i in range(40))
        for k in range(400):
            write(root, f"pkg{k % 20}/m{k}.py", body)
        t = time.time()
        subprocess.run([sys.executable, str(CODE_MAP), "--repo", str(root), "build"], capture_output=True, timeout=300)
        build_s = time.time() - t
        t = time.time()
        subprocess.run([sys.executable, str(CODE_MAP), "--repo", str(root), "find", "f39"], capture_output=True)
        query_s = time.time() - t
        check(build_s < 20 and query_s < 3, f"code-map: 400 files build {build_s:.1f}s, query {query_s:.2f}s")


if __name__ == "__main__":
    validate_skills()
    test_scripts()
    test_secret_scan()
    test_ci_and_packaging()
    test_hooks()
    test_live_modernize()
    test_code_map()
    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)
