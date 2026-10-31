#!/usr/bin/env python3
"""Audit a finished project from every angle and produce one scored report.

Usage:
  python3 project_audit.py [REPO] [--quick] [--offline] [--deep] [--out report.md] [--json]

Areas (each scored 0-100; areas that do not apply to the project type are N/A):
  build-test   project's own lint/typecheck/build/test (verify.py)       --quick skips
  tests        tests exist, are runnable, and are proportionate to the code
  security     secrets (scan_secrets.py) + insecure code patterns + sensitive files
  dependencies vulnerable/deprecated/outdated deps, runtimes (live)    --offline skips
  portability  "works on my machine" causes (portability_audit.py); --deep adds clean_room.py
  code-health  dead code, commented-out code, TODO debt, oversized files/functions
  docs         README quality (English or Bangla headings), LICENSE, CHANGELOG
  hygiene      .gitignore coverage, committed artifacts/binaries/large files
  ci           CI exists, runs tests and lint, dependency update bot
  errors       swallowed exceptions, empty catch blocks, stray debug output
  a11y         images without alt, unlabeled controls, zoom disabled (UI projects)
  release      version, signing, privacy policy, icons, metadata (apps and libraries)
  licenses     copyleft/unknown licenses among direct dependencies
  vault        PRD/STATE/TOKENS/STACK/SCHEMA/PLAN present, filled, in sync, routed from CLAUDE.md

Overall score = weighted mean of the areas that were checked; grade A-F; verdict
READY / READY WITH WARNINGS / NOT READY. Exit 1 when NOT READY.
Areas that could not be checked are listed as such, never counted as passed.
Standard library only (Python 3.11+).
"""
# audit: allow-file - this file defines detection patterns; scanning it would flag the rules themselves
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent
TOOLS = {"detect_stack.py": "codebase-recon", "verify.py": "verification-gate", "scan_secrets.py": "secret-scan",
         "portability_audit.py": "portable-project", "clean_room.py": "portable-project",
         "find_dead_code.py": "legacy-cleanup", "freshness_report.py": "live-modernize", "code_map.py": "code-map", "vault.py": "project-vault"}
PENALTY = {"critical": 35, "high": 15, "medium": 6, "low": 2}
ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}
AREAS = {  # name: (title, weight)
    "build-test": ("Build & tests pass", 18), "tests": ("Test coverage", 9), "security": ("Security", 18),
    "dependencies": ("Dependencies", 9), "portability": ("Portability", 7), "code-health": ("Code health", 6),
    "docs": ("Documentation", 6), "hygiene": ("Repo hygiene", 5), "ci": ("CI/CD", 5), "errors": ("Error handling", 4),
    "a11y": ("Accessibility", 4), "release": ("Release readiness", 9), "licenses": ("Licenses", 3),
    "vault": ("Project vault", 5)}
SKIP_PARTS = {"node_modules", ".venv", "venv", "dist", "build", "target", "vendor", ".dart_tool", ".gradle",
              "__pycache__", "out", "bin", "obj", ".next", "coverage", "Pods", ".claude"}
SRC_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".go", ".rs", ".java", ".kt",
           ".cs", ".dart", ".swift", ".c", ".h", ".cpp", ".hpp", ".ino", ".php", ".rb"}
TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec|specs|androidTest|integration_test)/|(^|/)test_[^/]+\.py$|"
                     r"_test\.(py|go|dart)$|\.(test|spec)\.[jt]sx?$|Tests?\.(java|kt|cs|swift)$|(^|/)(selftest|test)\.[a-z]+$")
ALLOW_RE = re.compile(r"audit:\s*allow|portability:\s*allow|secret-scan:\s*allow", re.I)
ALLOW_FILE_RE = re.compile(r"audit:\s*allow-file", re.I)  # in the first 40 lines: file defines rules/patterns

SECURITY_PATTERNS = [  # (severity, regex, problem, fix, extensions or None)
    ("high", r"\beval\(", "eval() executes arbitrary code", "parse data explicitly (JSON.parse/ast.literal_eval)",
     {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".php", ".rb"}),
    ("high", r"os\.system\([^)]*(\+|\{|%|format)", "shell command built from variables (command injection)",
     "use subprocess.run([...]) with an argument list", {".py"}),
    ("medium", r"shell\s*=\s*True", "subprocess with shell=True", "pass an argument list without shell=True", {".py"}),
    ("high", r"(?i)(execute|query|raw|executemany)\(\s*f[\"']|\b(SELECT|INSERT|UPDATE|DELETE)\b[^\"'\n]*[\"']\s*(\+|%\s|\.format\()",
     "SQL built by string formatting (SQL injection)", "use parameterised queries / the ORM's bind parameters", None),
    ("medium", r"dangerouslySetInnerHTML|\.innerHTML\s*=|\bv-html\b|\{@html\b", "raw HTML injection point (XSS)",
     "render text, or sanitise with DOMPurify before inserting HTML", None),
    ("high", r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|"
             r"InsecureSkipVerify\s*:\s*true|_create_unverified_context|ALLOW_ALL_HOSTNAME_VERIFIER|"
             r"badCertificateCallback\s*=.*=>\s*true|TrustAllCerts|trustAllCerts|ServerCertificateValidationCallback\s*=.*true",
     "TLS certificate verification disabled (man-in-the-middle)", "remove it; trust a specific CA if needed", None),
    ("high", r"android:debuggable\s*=\s*\"true\"", "debuggable release build", "remove android:debuggable", {".xml"}),
    ("medium", r"usesCleartextTraffic\s*=\s*\"true\"", "cleartext HTTP allowed app-wide",
     "use HTTPS, or a network-security-config limited to the local device/robot IP", {".xml"}),
    ("medium", r"^\s*DEBUG\s*=\s*True\b|\.run\([^)]*debug\s*=\s*True", "debug mode enabled in code",
     "read DEBUG from the environment, default off", {".py"}),
    ("medium", r"allow_origins\s*=\s*\[\s*[\"']\*|Access-Control-Allow-Origin[\"']?\s*[,:]\s*[\"']\*",
     "CORS allows any origin", "list the allowed origins explicitly", None),
    ("medium", r"pickle\.loads?\(|yaml\.load\((?![^)]*SafeLoader)(?![^)]*safe)", "unsafe deserialisation",
     "use json / yaml.safe_load; never unpickle untrusted data", {".py"}),
    ("medium", r"(?i)(md5|sha1)\s*\([^)]*pass", "weak hash used for passwords", "use bcrypt/argon2/scrypt", None),
    ("high", r"algorithms\s*=\s*\[?\s*[\"']none|verify_signature[\"']?\s*:\s*False", "JWT signature not verified",
     "always verify signatures with a fixed algorithm list", None),
    ("medium", r"chmod\s+(-R\s+)?777|0o?777\b", "world-writable permissions", "use the least permissive mode", None),
    ("low", r"Math\.random\(\)[^;\n]*(token|secret|password|key|otp|nonce)", "Math.random() for security values",
     "use crypto.getRandomValues / crypto.randomUUID", None),
    ("low", r"android:allowBackup\s*=\s*\"true\"", "app data included in device backups",
     "set allowBackup=false or define backup rules for sensitive data", {".xml"}),
]
ERROR_PATTERNS = [
    ("medium", r"except\s*:\s*\n\s*pass\b|except\s+(Exception|BaseException)\s*(as\s+\w+)?\s*:\s*\n\s*pass\b",
     "exception swallowed silently", "log it with context or let it propagate", {".py"}),
    ("medium", r"^\s*except\s*:", "bare except catches everything (incl. KeyboardInterrupt)",
     "catch the specific exception types", {".py"}),
    ("medium", r"catch\s*(\([^)]*\))?\s*\{\s*\}", "empty catch block",
     "handle, log or rethrow the error", {".js", ".jsx", ".ts", ".tsx", ".mjs", ".java", ".kt", ".cs", ".dart", ".swift", ".php"}),
    ("medium", r"\.catch\(\s*\(?\s*\w*\s*\)?\s*=>\s*(\{\s*\}|null|undefined)\s*\)", "promise rejection ignored",
     "handle or report the rejection", {".js", ".jsx", ".ts", ".tsx", ".mjs"}),
    ("medium", r"if\s+err\s*!=\s*nil\s*\{\s*\}|_\s*=\s*err\b", "Go error ignored", "return or handle err", {".go"}),
    ("low", r"\.unwrap\(\)", "unwrap() panics on error", "use ? or handle the error case", {".rs"}),
]
A11Y_PATTERNS = [
    ("medium", r"<img\b(?![^>]*\balt\s*=)[^>]*>", "image without alt text", "add alt=\"...\" (alt=\"\" if decorative)"),
    ("medium", r"<html\b(?![^>]*\blang\s*=)[^>]*>", "page language not declared", "add <html lang=\"en\"> (or bn)"),
    ("medium", r"user-scalable\s*=\s*no|maximum-scale\s*=\s*1(\.0)?\b", "zoom disabled", "allow pinch-zoom"),
    ("medium", r"<button\b(?![^>]*aria-label)[^>]*>\s*<(svg|i|img|Icon)\b", "icon-only button without a label",
     "add aria-label"),
    ("low", r"<(div|span)\b(?![^>]*\brole\s*=)[^>]*\bon[Cc]lick\s*=", "clickable div/span without role/keyboard support",
     "use <button>, or add role=\"button\" tabIndex={0} and key handlers"),
    ("low", r"<input\b(?![^>]*(aria-label|aria-labelledby|\bid\s*=|type\s*=\s*[\"']hidden))[^>]*>",
     "input without an associated label", "add a <label for> or aria-label"),
    ("low", r"outline\s*:\s*(none|0)\b", "focus outline removed", "provide a visible :focus-visible style"),
]
COPYLEFT = re.compile(r"(?i)\b(AGPL|SSPL|GPL|EUPL|OSL|CC-BY-NC|Commons Clause)")
WEAK_COPYLEFT = re.compile(r"(?i)\b(LGPL|MPL|EPL|CDDL)")


# ------------------------------------------------------------------ helpers
def tool(name: str) -> Path | None:
    for cand in (HERE / name, SKILLS / TOOLS[name] / "scripts" / name):
        if cand.exists():
            return cand
    return None


def load(name: str):
    path = tool(name)
    if not path:
        return None
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name[:-3]] = mod
    spec.loader.exec_module(mod)
    return mod


def run(args: list[str], cwd: Path, timeout: int = 1800) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


class Audit:
    def __init__(self, repo: Path, args):
        self.repo, self.args = repo, args
        self.findings: list[dict] = []
        self.status: dict[str, str] = {}      # area -> "checked" | "n/a" | "not checked: reason"
        self.notes: dict[str, list[str]] = {}
        out = run(["git", "ls-files", "-z"], repo)
        self.is_git = bool(out and out.returncode == 0)
        files = [f for f in (out.stdout.split("\0") if self.is_git else []) if f]
        if not self.is_git:
            files = [str(p.relative_to(repo)).replace("\\", "/") for p in repo.rglob("*") if p.is_file()
                     and not set(p.relative_to(repo).parts) & (SKIP_PARTS | {".git"})]
        self.tracked = files
        self.src = [f for f in files if Path(f).suffix in SRC_EXT and not set(f.split("/")[:-1]) & SKIP_PARTS
                    and not f.endswith((".min.js", ".d.ts", ".g.dart", ".freezed.dart", "_pb2.py"))]
        self.tests = [f for f in self.src if TEST_RE.search(f)]
        self.prod = [f for f in self.src if f not in self.tests]
        # heuristics skip files that define detection rules (marked `audit: allow-file`)
        self.scannable = [f for f in self.prod if not ALLOW_FILE_RE.search("\n".join(self.read(f).splitlines()[:40]))]
        det = load("detect_stack.py")
        self.projects = det.detect(repo)["projects"] if det else []
        self.types = self.classify()

    def add(self, area, sev, where, problem, fix):
        self.findings.append({"area": area, "severity": sev, "where": where, "problem": problem, "fix": fix})

    def read(self, rel: str) -> str:
        try:
            return (self.repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def has(self, *names) -> str | None:
        return next((n for n in names if (self.repo / n).exists()), None)

    def json_file(self, rel: str) -> dict:
        try:
            return json.loads(self.read(rel) or "{}")
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------- project type
    def classify(self) -> set[str]:
        t = set()
        for p in self.projects:
            fw = set(p.get("frameworks", []))
            s = p["stack"]
            if s in ("flutter", "android-gradle") or fw & {"react-native", "expo"}:
                t.add("mobile")
            if s in ("platformio", "arduino"):
                t.add("embedded")
            if fw & {"electron"} or any(f.endswith((".iss", "electron-builder.yml", ".spec")) for f in self.tracked) \
                    or any(re.search(r"<(UseWPF|UseWindowsForms)>true", self.read(f)) for f in self.tracked if f.endswith(".csproj")):
                t.add("desktop")
            if fw & {"react", "next", "vue", "svelte", "vite"}:
                t.add("web")
            if fw & {"express", "fastify", "nestjs", "@nestjs/core"}:
                t.add("api")
            if s == "node":
                pkg = self.json_file(p["root"] + "/package.json" if p["root"] != "." else "package.json")
                if pkg.get("bin"):
                    t.add("cli")
                if (pkg.get("main") or pkg.get("exports")) and not t & {"web", "api", "mobile", "desktop"}:
                    t.add("library")
            if s == "python":
                py = self.toml(p["root"], "pyproject.toml")
                deps = " ".join(py.get("project", {}).get("dependencies", [])) + self.read(
                    (p["root"] + "/" if p["root"] != "." else "") + "requirements.txt")
                if re.search(r"(?i)\b(fastapi|flask|django|starlette|aiohttp|sanic|litestar)\b", deps):
                    t.add("api")
                if py.get("project", {}).get("scripts"):
                    t.add("cli")
                if py.get("project", {}).get("name") and not t & {"api", "cli"}:
                    t.add("library")
            if s == "go" and any(f.endswith("main.go") for f in self.tracked):
                t.add("cli" if not re.search(r"net/http|gin-gonic|labstack/echo|gofiber",
                                             " ".join(self.read(f) for f in self.src if f.endswith(".go"))) else "api")
            if s == "rust":
                t.add("cli" if any(f.endswith("src/main.rs") for f in self.tracked) else "library")
            if s == "dotnet" and "desktop" not in t:
                t.add("api" if any("Microsoft.NET.Sdk.Web" in self.read(f) for f in self.tracked if f.endswith(".csproj")) else "app")
        app_roots = [p["root"] + "/" for p in self.projects if p["stack"] in ("flutter", "android-gradle")
                     and p["root"] != "."]
        if any(f.endswith((".html", ".jsx", ".tsx", ".vue", ".svelte")) and not f.startswith(tuple(app_roots) or ("\0",))
               and not set(f.split("/")[:-1]) & SKIP_PARTS for f in self.tracked):
            if not (t & {"mobile", "desktop"}) or app_roots:
                t.add("web")
        return t or {"generic"}

    def toml(self, root: str, name: str) -> dict:
        if not tomllib:
            return {}
        try:
            return tomllib.loads(self.read((root + "/" if root != "." else "") + name) or "")
        except Exception:
            return {}

    def ui(self) -> bool:
        return bool(self.types & {"web", "mobile", "desktop"})

    def app(self) -> bool:
        return bool(self.types & {"web", "mobile", "desktop", "api", "cli", "app", "embedded"})

    # -------------------------------------------------------------- scanners
    def scan_patterns(self, area: str, patterns, files: list[str], cap: int = 25) -> None:
        count = 0
        for f in files:
            text = self.read(f)
            if not text or len(text) > 800_000 or ALLOW_FILE_RE.search("\n".join(text.splitlines()[:40])):
                continue
            lines = text.splitlines()
            for sev, rx, problem, fix, *exts in patterns:
                ext = exts[0] if exts else None
                if ext and Path(f).suffix not in ext:
                    continue
                for m in re.finditer(rx, text, re.M):
                    ln = text[:m.start()].count("\n") + 1
                    if any(ALLOW_RE.search(lines[i]) for i in (ln - 1, ln - 2) if 0 <= i < len(lines)):
                        continue
                    self.add(area, sev, f"{f}:{ln}", problem, fix)
                    count += 1
                    if count >= cap:
                        return
                    break  # one hit per pattern per file is enough to act on

    # -------------------------------------------------------------- areas
    def area_build_test(self) -> None:
        if self.args.quick:
            self.status["build-test"] = "not checked: --quick"
            return
        v = tool("verify.py")
        if not v or not self.projects:
            self.status["build-test"] = "not checked: no buildable project detected" if v else "not checked: verify.py missing"
            return
        out = run([sys.executable, str(v), str(self.repo), "--timeout", "900"], self.repo, 3600)
        if out is None:
            self.status["build-test"] = "not checked: timed out"
            return
        rows = re.findall(r"^(PASS|FAIL|SKIP)\s+(\S+)\s+(.*)$", out.stdout, re.M)
        passed = [r for r in rows if r[0] == "PASS"]
        for st, label, detail in rows:
            if st == "FAIL":
                sev = "critical" if label.endswith((":build", ":test")) else "high"
                self.add("build-test", sev, label, f"`{detail.split(' (')[0]}` fails",
                         "fix the failure (root-cause-debug); see verify.py output")
        if not passed and not any(r[0] == "FAIL" for r in rows):
            self.status["build-test"] = "not checked: every check was skipped (tools missing)"
            self.notes.setdefault("build-test", []).extend(f"{l}: {d}" for s, l, d in rows if s == "SKIP")
            return
        for st, label, detail in rows:
            if st == "SKIP" and "not installed" in detail:
                self.notes.setdefault("build-test", []).append(f"{label} skipped: {detail}")
        self.status["build-test"] = "checked"

    def area_tests(self) -> None:
        if not self.prod:
            self.status["tests"] = "n/a"
            return
        self.status["tests"] = "checked"
        n_src, n_test = len(self.prod), len(self.tests)
        ci_text = " ".join(self.read(f) for f in self.tracked if re.match(r"\.github/workflows/|\.gitlab-ci", f))
        has_cmd = any(p["commands"].get("test") for p in self.projects) or bool(
            re.search(r"(?i)\btest\b|pytest|selftest|vitest|jest", ci_text))
        if n_test == 0:
            self.add("tests", "high", ".", f"no automated tests for {n_src} source files",
                     "add tests for the core logic first (test-strategy)")
        elif n_test / n_src < 0.1:
            self.add("tests", "medium", ".", f"{n_test} test files for {n_src} source files", "cover the critical paths")
        elif n_test / n_src < 0.25:
            self.add("tests", "low", ".", f"{n_test} test files for {n_src} source files", "extend coverage")
        if n_test and not has_cmd and not self.types & {"embedded"}:
            self.add("tests", "medium", ".", "tests exist but no test command is defined",
                     "add a `test` script/target so everyone and CI run them the same way")
        tested_dirs = {f.split("/")[0] for f in self.tests}
        untested = sorted({f.split("/")[0] for f in self.prod if "/" in f} - tested_dirs)
        if n_test and untested and len(self.projects) > 1:
            self.add("tests", "low", ", ".join(untested[:5]), "parts of the repository without any tests",
                     "add at least smoke tests per project")
        self.notes["tests"] = [f"{n_test} test files, {n_src} source files"]

    def area_security(self) -> None:
        self.status["security"] = "checked"
        scan = tool("scan_secrets.py")
        if scan:
            out = run([sys.executable, str(scan), str(self.repo), "--mode", "all"], self.repo, 600)
            for line in (out.stdout.splitlines() if out else []):
                m = re.match(r"^(\S+?):(\d+)\s+(.+?):\s", line)
                if m:
                    self.add("security", "critical", f"{m.group(1)}:{m.group(2)}", f"{m.group(3)} in the repository",
                             "move to env/secret storage and ROTATE it (it is in git history)")
        else:
            self.notes.setdefault("security", []).append("secret scan not available")
        sensitive = re.compile(r"(^|/)(\.env(\.[\w-]+)?|[^/]+\.env|id_(rsa|ed25519|ecdsa)|[^/]+\.(pem|key|p12|pfx|jks|keystore)|"
                               r"credentials\.json|service[-_]account[^/]*\.json|google-services\.json|GoogleService-Info\.plist)$")
        for f in self.tracked:
            if sensitive.search(f) and not re.search(r"\.(example|sample|template|dist)$", f):
                sev = "medium" if f.endswith(("google-services.json", "GoogleService-Info.plist")) else "critical"
                self.add("security", sev, f, "sensitive file committed",
                         "remove from git (git rm --cached), add to .gitignore, rotate the credential")
        prod_all = self.prod + [f for f in self.tracked if f.endswith(".xml") and "AndroidManifest" in f]
        self.scan_patterns("security", SECURITY_PATTERNS, prod_all)
        for f in self.prod:
            if ALLOW_FILE_RE.search("\n".join(self.read(f).splitlines()[:40])):
                continue
            for m in re.finditer(r"[\"'](http://(?!localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|"
                                 r"\[::1\]|www\.w3\.org|schemas\.|example\.)[^\"'\s]+)", self.read(f)):
                self.add("security", "low", f, f"plain-HTTP URL {m.group(1)[:60]}", "use https://")
                break
        if self.types & {"web", "api"} and not any(Path(f).name.lower() in ("security.md",) for f in self.tracked):
            self.add("security", "low", ".", "no SECURITY.md (how to report vulnerabilities)", "add SECURITY.md")

    def area_dependencies(self) -> None:
        if self.args.offline:
            self.status["dependencies"] = "not checked: --offline"
            return
        fr = tool("freshness_report.py")
        if not fr:
            self.status["dependencies"] = "not checked: freshness_report.py missing"
            return
        out = run([sys.executable, str(fr), str(self.repo), "--json", "--cache-ttl", "3600"], self.repo, 600)
        try:
            rep = json.loads(out.stdout) if out else None
        except json.JSONDecodeError:
            rep = None
        if not rep:
            self.status["dependencies"] = "not checked: live sources unavailable"
            return
        deps = rep.get("deps", [])
        if not deps and not rep.get("runtimes"):
            self.status["dependencies"] = "n/a"
            return
        self.status["dependencies"] = "checked"
        unknown = 0
        for d in deps:
            where = f"{d['manifest']} {d['name']} {d['current']}"
            if d.get("vulns"):
                self.add("dependencies", "critical" if d.get("exact") else "high", where,
                         f"{len(d['vulns'])} known vulnerabilit{'y' if len(d['vulns']) == 1 else 'ies'} ({d['vulns'][0][:80]})",
                         f"upgrade to a fixed version (latest {d.get('latest')}) - live-modernize")
            elif d.get("deprecated"):
                self.add("dependencies", "high", where, f"deprecated: {d['deprecated'][:90]}",
                         "replace with the maintained successor")
            elif d.get("kind") == "major":
                self.add("dependencies", "low", where, f"major version behind (latest {d['latest']})",
                         "plan the upgrade with its migration guide")
            if d.get("error"):
                unknown += 1
        for r in rep.get("runtimes", []):
            if r.get("kind") == "major":
                self.add("dependencies", "medium", r["declared_in"], f"{r['runtime']} {r['current']} is a major line behind "
                         f"(current {r['latest']})", "move to the current LTS/stable line")
        srcs = [f"{k}: {v}" for k, v in rep.get("vuln_sources", {}).items() if "unavailable" in v]
        if srcs or unknown:
            self.notes["dependencies"] = srcs + ([f"{unknown} dependencies not checked (registry unreachable)"] if unknown else [])

    def area_portability(self) -> None:
        pa = tool("portability_audit.py")
        if not pa:
            self.status["portability"] = "not checked: portability_audit.py missing"
            return
        out = run([sys.executable, str(pa), str(self.repo), "--json"], self.repo, 600)
        try:
            items = json.loads(out.stdout)["findings"] if out else []
        except (json.JSONDecodeError, KeyError):
            self.status["portability"] = "not checked: audit failed"
            return
        self.status["portability"] = "checked"
        for f in items:
            self.add("portability", f["severity"], f["where"], f"[{f['kind']}] {f['problem']}", f["fix"])
        if self.args.deep and tool("clean_room.py") and self.projects:
            cr = run([sys.executable, str(tool("clean_room.py")), str(self.repo), "--compare"], self.repo, 3600)
            for m in re.finditer(r"^\s+(\S+)\s+here=PASS\s+clean-room=FAIL", cr.stdout if cr else "", re.M):
                self.add("portability", "critical", m.group(1), "passes here but fails on a clean machine",
                         "see clean_room.py output (portable-project)")
            self.notes.setdefault("portability", []).append("clean-room comparison run" if cr else "clean room timed out")

    def area_code_health(self) -> None:
        if not self.prod:
            self.status["code-health"] = "n/a"
            return
        self.status["code-health"] = "checked"
        dc = tool("find_dead_code.py")
        if dc:
            out = run([sys.executable, str(dc), str(self.repo), "--no-tools", "--limit", "0"], self.repo, 600)
            counts = dict(re.findall(r"^## (Symbols|Files|Deprecated|Commented)[^(]*\((\d+)\)", out.stdout if out else "", re.M))
            labels = {"Symbols": ("unreferenced functions/classes", "legacy-cleanup"),
                      "Files": ("files nothing references", "legacy-cleanup"),
                      "Commented": ("commented-out code blocks", "delete them; git keeps history"),
                      "Deprecated": ("deprecated/legacy markers", "finish the migration and remove")}
            for key, n in counts.items():
                n = int(n)
                if n:
                    sev = "medium" if n >= 15 and key != "Deprecated" else "low"
                    self.add("code-health", sev, ".", f"{n} {labels[key][0]}", labels[key][1])
        todo = sum(len(re.findall(r"\b(TODO|FIXME|HACK|XXX)\b", self.read(f))) for f in self.scannable)
        if todo:
            self.add("code-health", "medium" if todo > 25 else "low", ".", f"{todo} TODO/FIXME/HACK markers",
                     "resolve or turn into tracked issues")
        cm = load("code_map.py")
        big_files, big_funcs = [], []
        for f in self.prod:
            text = self.read(f)
            n = text.count("\n")
            if n > 800:
                big_files.append(f"{f} ({n} lines)")
            if cm:
                try:
                    for kind, name, a, b, _ in cm.parse_file(self.repo, f)["symbols"]:
                        if kind in ("function", "method") and b - a > 120:
                            big_funcs.append(f"{f}:{a} {name} ({b - a + 1} lines)")
                except (OSError, ValueError, SyntaxError, RecursionError) as exc:
                    self.notes.setdefault("code-health", []).append(f"{f}: not parsed ({type(exc).__name__})")
        if big_files:
            self.add("code-health", "low" if len(big_files) < 5 else "medium", "; ".join(big_files[:4]),
                     f"{len(big_files)} source file(s) over 800 lines", "split by responsibility (safe-refactor)")
        if big_funcs:
            self.add("code-health", "low" if len(big_funcs) < 5 else "medium", "; ".join(big_funcs[:4]),
                     f"{len(big_funcs)} function(s) over 120 lines", "extract smaller functions (safe-refactor)")

    def area_docs(self) -> None:
        self.status["docs"] = "checked"
        readme = self.has("README.md", "README.rst", "README.txt", "README", "readme.md")
        if not readme:
            self.add("docs", "high", ".", "no README", "add README: what it is, install/setup, usage, build/test")
        else:
            text = self.read(readme)
            heads = " ".join(re.findall(r"^#+\s*(.+)$", text, re.M)).lower() + " " + text[:3000].lower()
            if text.count("\n") < 15:
                self.add("docs", "medium", readme, "README is very short", "describe setup, usage and development")
            if not re.search(r"install|setup|getting started|quick ?start|requirement|ইন্সটল|ইনস্টল|সেটআপ|শুরু|প্রয়োজন", heads):
                self.add("docs", "medium", readme, "no install/setup section", "add step-by-step setup from a fresh clone")
            if not re.search(r"usage|how to|run|example|ব্যবহার|চালা", heads):
                self.add("docs", "low", readme, "no usage section", "show how to run/use it with an example")
            if self.projects and self.app() and not re.search(r"test|build|develop|contribut|টেস্ট|বিল্ড|উন্নয়ন", heads):
                self.add("docs", "low", readme, "no build/test instructions for developers", "add a Development section")
        if not self.has("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENCE"):
            self.add("docs", "medium", ".", "no LICENSE file (others may not legally use it)",
                     "add a LICENSE (MIT/Apache-2.0/proprietary notice)")
        if (self.app() or "library" in self.types) and not self.has("CHANGELOG.md", "CHANGELOG", "CHANGES.md", "HISTORY.md"):
            self.add("docs", "low", ".", "no CHANGELOG", "keep a CHANGELOG.md (Keep a Changelog format)")

    def area_hygiene(self) -> None:
        self.status["hygiene"] = "checked"
        gi = self.read(".gitignore")
        if not gi and self.is_git:
            self.add("hygiene", "high", ".gitignore", "no .gitignore", "add the official template for each stack")
        stacks = {p["stack"] for p in self.projects}
        need = {"node": ["node_modules"], "python": ["__pycache__", ".venv|venv"], "flutter": [".dart_tool", "build"],
                "dart": [".dart_tool"], "android-gradle": [".gradle", "local.properties", "build"],
                "gradle": [".gradle", "build"], "rust": ["target"], "dotnet": ["bin", "obj"], "go": [],
                "platformio": [".pio"], "maven": ["target"]}
        all_gi = gi + "".join(self.read(f) for f in self.tracked if f.endswith("/.gitignore"))
        for s in stacks:
            for pat in need.get(s, []):
                if not re.search(rf"(^|/)({pat})/?\s*$", all_gi, re.M):
                    self.add("hygiene", "medium", ".gitignore", f"`{pat.split('|')[0]}` not ignored ({s})",
                             f"add `{pat.split('|')[0]}/` to .gitignore")
        if not re.search(r"^/?\.env\b|^\*\.env", all_gi, re.M) \
                and any(re.search(r"load_dotenv|require\(['\"]dotenv|from ['\"]dotenv|import ['\"]dotenv|flutter_dotenv|DotNetEnv",
                              self.read(f)) for f in self.scannable[:300]):
            self.add("hygiene", "low", ".gitignore", "`.env` not ignored although env config is used", "add `.env` to .gitignore")
        artifact = re.compile(r"(^|/)(node_modules|__pycache__|\.venv|venv|\.dart_tool|\.gradle|\.pio|coverage|\.next|"
                              r"\.pytest_cache)/|\.pyc$|(^|/)(\.DS_Store|Thumbs\.db)$")
        arts = [f for f in self.tracked if artifact.search(f)]
        if arts:
            self.add("hygiene", "high", arts[0], f"{len(arts)} generated/cache files committed",
                     "git rm -r --cached them and ignore the folders")
        binary = re.compile(r"\.(apk|aab|ipa|exe|msi|dmg|deb|rpm|zip|7z|rar|tar\.gz|so|dll|dylib|class|o|obj)$", re.I)
        bins = [f for f in self.tracked if binary.search(f) and not f.endswith("gradle-wrapper.jar")]
        if bins:
            self.add("hygiene", "medium", ", ".join(bins[:3]), f"{len(bins)} build output/binary file(s) in git",
                     "publish binaries as release assets, not commits")
        big = []
        for f in self.tracked:
            try:
                size = (self.repo / f).stat().st_size
            except OSError:
                continue
            if size > 5_000_000:
                big.append(f"{f} ({size // 1_000_000} MB)")
        if big:
            self.add("hygiene", "medium", "; ".join(big[:3]), f"{len(big)} file(s) larger than 5 MB in git",
                     "use Git LFS or external storage")
        if self.is_git and not self.has(".gitattributes") and any(f.endswith((".sh", ".bat", ".cmd")) for f in self.tracked):
            self.add("hygiene", "low", ".gitattributes", "no .gitattributes for line endings", "see portable-project")

    def area_ci(self) -> None:
        if not self.projects and not self.src:
            self.status["ci"] = "n/a"
            return
        self.status["ci"] = "checked"
        wfs = [f for f in self.tracked if re.match(r"\.github/workflows/.+\.ya?ml$", f)]
        others = [f for f in (".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", "bitbucket-pipelines.yml",
                              ".circleci/config.yml", "codemagic.yaml", "bitrise.yml") if f in self.tracked]
        if not wfs and not others:
            self.add("ci", "medium", ".", "no CI: nothing checks changes automatically",
                     "generate one from the project's commands (ci-setup: gen_ci.py)")
            return
        text = " ".join(self.read(f) for f in wfs + others).lower()
        if not re.search(r"\btest\b|pytest|unittest|vitest|jest|mocha|go test|cargo test|flutter test|gradlew\s+\w*test|"
                         r"dotnet test|selftest|npm (run )?test|ctest|phpunit|rspec", text):
            self.add("ci", "medium", ", ".join((wfs + others)[:2]), "CI does not run the tests", "add the test command")
        if not re.search(r"lint|analyze|clippy|ruff|eslint|vet|flake8|ktlint|detekt", text):
            self.add("ci", "low", ", ".join((wfs + others)[:2]), "CI does not lint", "add the lint command")
        if self.projects and not self.has(".github/dependabot.yml", ".github/dependabot.yaml", "renovate.json", ".github/renovate.json",
                        "renovate.json5"):
            self.add("ci", "low", ".github/", "no automated dependency updates",
                     "add .github/dependabot.yml (or Renovate) for each ecosystem")

    def area_errors(self) -> None:
        if not self.prod:
            self.status["errors"] = "n/a"
            return
        self.status["errors"] = "checked"
        self.scan_patterns("errors", ERROR_PATTERNS, self.prod)
        if self.types & {"web", "api", "mobile"}:
            logs = [(f, len(re.findall(r"\bconsole\.log\(", self.read(f)))) for f in self.prod
                    if Path(f).suffix in (".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte")]
            total = sum(n for _, n in logs)
            if total > 10:
                worst = max(logs, key=lambda x: x[1])[0]
                self.add("errors", "low", worst, f"{total} console.log calls in production code",
                         "use a logger with levels, or remove debug output")
            prints = [f for f in self.prod if f.endswith(".dart") and re.search(r"^\s*print\(", self.read(f), re.M)]
            if len(prints) > 3:
                self.add("errors", "low", prints[0], f"print() in {len(prints)} Dart files",
                         "use debugPrint/a logger (print() output ships in release logs)")

    def area_a11y(self) -> None:
        ui_files = [f for f in self.tracked if f.endswith((".html", ".jsx", ".tsx", ".vue", ".svelte", ".css", ".scss"))
                    and not set(f.split("/")[:-1]) & SKIP_PARTS and not TEST_RE.search(f)]
        dart = [f for f in self.prod if f.endswith(".dart")]
        if not self.ui() or not (ui_files or dart):
            self.status["a11y"] = "n/a"
            return
        self.status["a11y"] = "checked"
        self.scan_patterns("a11y", [p + (None,) for p in A11Y_PATTERNS], ui_files)
        if dart:
            icon = sum(len(re.findall(r"\bIconButton\(", self.read(f))) for f in dart)
            tips = sum(len(re.findall(r"\btooltip\s*:", self.read(f))) for f in dart)
            if icon > tips:
                self.add("a11y", "low", "lib/", f"{icon - tips} IconButton(s) without tooltip (screen readers announce nothing)",
                         "add tooltip: or a Semantics label")
            imgs = sum(len(re.findall(r"\bImage\.(asset|network)\(", self.read(f))) for f in dart)
            sem = sum(len(re.findall(r"semanticLabel\s*:", self.read(f))) for f in dart)
            if imgs > sem + 2:
                self.add("a11y", "low", "lib/", f"{imgs - sem} images without semanticLabel", "add semanticLabel or excludeFromSemantics")

    def area_release(self) -> None:
        if not (self.app() or "library" in self.types):
            self.status["release"] = "n/a"
            return
        self.status["release"] = "checked"
        seen_gradle: set[str] = set()
        for p in self.projects:
            r = "" if p["root"] == "." else p["root"] + "/"
            s = p["stack"]
            if s == "node":
                pkg = self.json_file(r + "package.json")
                if not pkg.get("version") and not pkg.get("private"):
                    self.add("release", "medium", r + "package.json", "no version", "set \"version\" (semver)")
                if "library" in self.types:
                    for k in ("description", "license", "repository"):
                        if not pkg.get(k):
                            self.add("release", "low", r + "package.json", f"no `{k}` field", f"add \"{k}\"")
                    if not (pkg.get("types") or pkg.get("typings") or any(f.endswith(".d.ts") for f in self.tracked)) \
                            and any(f.endswith((".ts", ".tsx")) for f in self.src):
                        self.add("release", "low", r + "package.json", "TypeScript library without type declarations",
                                 "emit .d.ts and set \"types\"")
                if self.types & {"web"} and not (pkg.get("scripts") or {}).get("build"):
                    self.add("release", "medium", r + "package.json", "no production build script", "add \"build\"")
            elif s == "python":
                py = self.toml(p["root"], "pyproject.toml")
                proj = py.get("project", {})
                if proj and not (proj.get("version") or "version" in proj.get("dynamic", [])):
                    self.add("release", "medium", r + "pyproject.toml", "no version", "set project.version")
                if "library" in self.types and proj:
                    for k in ("description", "readme", "license"):
                        if not proj.get(k):
                            self.add("release", "low", r + "pyproject.toml", f"no project.{k}", f"add {k}")
            elif s == "flutter":
                spec = self.read(r + "pubspec.yaml")
                if not re.search(r"^version:\s*\d", spec, re.M):
                    self.add("release", "high", r + "pubspec.yaml", "no app version", "set version: 1.0.0+1")
            if s in ("android-gradle", "flutter"):
                gfiles = [f for f in self.tracked if re.search(r"(^|/)app/build\.gradle(\.kts)?$", f)
                          and f.startswith(r) and f not in seen_gradle]
                seen_gradle.update(gfiles)
                gradle = "".join(self.read(f) for f in gfiles)
                where = gfiles[0] if gfiles else r
                if gradle:
                    if re.search(r"signingConfig\s*=?\s*signingConfigs\.(getByName\(\s*\"debug\"\s*\)|debug)", gradle):
                        self.add("release", "high", where, "release build signed with the debug key",
                                 "create signingConfigs.release (keystore path/passwords from key.properties or env)")
                    elif not re.search(r"signingConfigs\s*\{[^}]*release|create\(\s*\"release\"", gradle, re.S):
                        self.add("release", "high", where, "no release signing config (release builds are unsigned)",
                                 "add signingConfigs.release reading the keystore path/passwords from key.properties or env")
                    if not re.search(r"(minifyEnabled|isMinifyEnabled)\s*=?\s*true", gradle):
                        self.add("release", "low", r + "android/app/build.gradle", "code shrinking (R8) disabled for release",
                                 "enable minify + shrinkResources after testing")
                if gfiles and not any(re.search(r"mipmap-[a-z]*hdpi/ic_launcher", f) for f in self.tracked) and \
                        "flutter_launcher_icons" not in self.read(r + "pubspec.yaml"):
                    self.add("release", "low", r or ".", "no launcher icon found", "add app icons (flutter_launcher_icons)")
        if "mobile" in self.types:
            corpus = " ".join(self.read(f) for f in self.tracked if re.search(r"(?i)readme|privacy|strings\.xml|\.arb$", f))
            if not re.search(r"(?i)privacy|গোপনীয়তা", corpus):
                self.add("release", "medium", ".", "no privacy policy reference (required by Play Store / App Store)",
                         "publish a privacy policy page and link it in the app and store listing")
        if "desktop" in self.types:
            corpus = " ".join(self.read(f) for f in self.tracked if f.endswith((".iss", ".yml", ".yaml", ".json", ".spec", ".md")))
            if not re.search(r"(?i)SignTool|signtool|certificateFile|CSC_LINK|codesign|sign_?tool|osx[Ss]ign|win:.*sign", corpus):
                self.add("release", "low", ".", "installer not code-signed (SmartScreen/Gatekeeper warnings)",
                         "sign Windows installers (Authenticode) and notarise macOS builds when distributing widely")
        if self.is_git and self.app():
            tags = run(["git", "tag", "--list"], self.repo)
            if tags and not tags.stdout.strip():
                self.add("release", "low", ".", "no git tags for releases", "tag each release (v1.2.0)")

    def area_licenses(self) -> None:
        own = (self.read("LICENSE") or self.read("LICENSE.md") or self.read("LICENSE.txt"))[:400]
        own_copyleft = bool(COPYLEFT.search(own))
        checked = unknown = 0
        for p in self.projects:
            r = self.repo / p["root"]
            if p["stack"] == "node":
                pkg = self.json_file(("" if p["root"] == "." else p["root"] + "/") + "package.json")
                for name in pkg.get("dependencies", {}):
                    meta = r / "node_modules" / name / "package.json"
                    if not meta.exists():
                        unknown += 1
                        continue
                    checked += 1
                    try:
                        lic = json.loads(meta.read_text(encoding="utf-8", errors="replace")).get("license", "")
                    except json.JSONDecodeError:
                        lic = ""
                    lic = lic if isinstance(lic, str) else str(lic.get("type", "")) if isinstance(lic, dict) else ""
                    self.license_finding(name, lic, own_copyleft, p["root"])
            elif p["stack"] == "python":
                try:
                    from importlib import metadata
                except ImportError:
                    continue
                py = self.toml(p["root"], "pyproject.toml")
                names = [re.match(r"[A-Za-z0-9][\w.-]*", d).group(0) for d in py.get("project", {}).get("dependencies", [])
                         if re.match(r"[A-Za-z0-9]", d)]
                for req in (r / "requirements.txt",):
                    names += [m.group(0) for line in (req.read_text(encoding="utf-8", errors="replace").splitlines()
                                                      if req.exists() else [])
                              if (m := re.match(r"[A-Za-z0-9][\w.-]*", line.strip()))]
                for name in names:
                    try:
                        md = metadata.metadata(name)
                    except metadata.PackageNotFoundError:
                        unknown += 1
                        continue
                    checked += 1
                    lic = (md.get("License-Expression") or md.get("License") or "") + " " + \
                        " ".join(c for c in md.get_all("Classifier") or [] if c.startswith("License"))
                    self.license_finding(name, lic, own_copyleft, p["root"])
        if not checked:
            self.status["licenses"] = "not checked: dependencies not installed locally" if unknown else "n/a"
            return
        self.status["licenses"] = "checked"
        if unknown:
            self.notes["licenses"] = [f"{checked} checked, {unknown} not installed locally (not checked)"]

    def license_finding(self, name, lic, own_copyleft, root):
        lic = (lic or "").strip()
        if not lic or lic.upper() in ("UNKNOWN", "SEE LICENSE IN LICENSE", "UNLICENSED"):
            self.add("licenses", "low", f"{root}: {name}", "dependency without a declared license",
                     "check its repository; avoid if unlicensed")
        elif COPYLEFT.search(lic) and not WEAK_COPYLEFT.search(lic) and not own_copyleft:
            sev = "high" if re.search(r"(?i)AGPL|SSPL|NC", lic) else "medium"
            self.add("licenses", sev, f"{root}: {name}", f"copyleft license `{lic[:40]}`",
                     "distributing your app may oblige you to release its source; replace it or get legal advice")

    def area_vault(self) -> None:
        if not self.src and not self.projects:
            self.status["vault"] = "n/a"
            return
        v = tool("vault.py")
        if not v:
            self.status["vault"] = "not checked: vault.py missing"
            return
        out = run([sys.executable, str(v), "check", str(self.repo), "--json"], self.repo, 600)
        try:
            items = json.loads(out.stdout)["findings"] if out else None
        except (json.JSONDecodeError, KeyError):
            items = None
        if items is None:
            self.status["vault"] = "not checked: vault check failed"
            return
        self.status["vault"] = "checked"
        for f in items:
            self.add("vault", f["severity"], f["where"], f["problem"], f["fix"] + " (project-vault)")

    # -------------------------------------------------------------- scoring
    def score(self) -> dict:
        areas = {}
        for key, (title, weight) in AREAS.items():
            st = self.status.get(key, "n/a")
            fs = [f for f in self.findings if f["area"] == key]
            if st != "checked":
                areas[key] = {"title": title, "status": st, "score": None, "findings": fs, "weight": weight}
                continue
            per_kind: dict[tuple, int] = {}
            pen = 0
            for f in fs:
                k = (f["severity"], f["problem"][:40])
                cap = PENALTY[f["severity"]] * 2.5
                add = min(PENALTY[f["severity"]], max(0, cap - per_kind.get(k, 0)))
                per_kind[k] = per_kind.get(k, 0) + add
                pen += add
            s = max(0, round(100 - pen))
            if any(f["severity"] == "critical" for f in fs):
                s = min(s, 40)
            areas[key] = {"title": title, "status": st, "score": s, "findings": fs, "weight": weight}
        scored = [a for a in areas.values() if a["score"] is not None]
        overall = round(sum(a["score"] * a["weight"] for a in scored) / sum(a["weight"] for a in scored)) if scored else None
        crit = [f for f in self.findings if f["severity"] == "critical"]
        high = [f for f in self.findings if f["severity"] == "high"]
        if overall is not None:  # serious problems cap the grade however good the rest is
            cap = 49 if crit else 64 if len(high) >= 6 else 74 if len(high) >= 3 else 84 if high else 100
            overall = min(overall, cap)
        blockers = crit + [f for f in high if f["area"] in ("security", "build-test", "release", "dependencies")]
        if len(high) >= 5:
            blockers = blockers or high
        unverified_build = areas["build-test"]["score"] is None and not self.args.quick and self.projects
        if blockers:
            verdict = "NOT READY"
        elif high or unverified_build or overall is None or overall < 70:
            verdict = "READY WITH WARNINGS"
        else:
            verdict = "READY"
        return {"overall": overall, "grade": grade(overall), "verdict": verdict, "areas": areas,
                "blockers": len(blockers), "counts": {s: sum(1 for f in self.findings if f["severity"] == s) for s in ORDER}}


def grade(s: int | None) -> str:
    if s is None:
        return "-"
    return "A" if s >= 90 else "B" if s >= 80 else "C" if s >= 70 else "D" if s >= 60 else "F"


def render(a: Audit, res: dict) -> str:
    name = a.repo.name
    stacks = sorted({p["stack"] + ("" if p["root"] == "." else " (" + p["root"] + ")") for p in a.projects})
    L = [f"# Project audit: {name}", "",
         f"Date: {dt.date.today().isoformat()} - type: {', '.join(sorted(a.types))} - stacks: "
         + (", ".join(stacks) or "none detected"), "",
         f"**Overall: {res['overall'] if res['overall'] is not None else '-'}/100 (grade {res['grade']}) - "
         f"verdict: {res['verdict']}**",
         f"Findings: {res['counts']['critical']} critical, {res['counts']['high']} high, "
         f"{res['counts']['medium']} medium, {res['counts']['low']} low", "",
         "| Area | Score | Grade | Findings | Status |", "|---|---|---|---|---|"]
    for key, ar in res["areas"].items():
        sc = "-" if ar["score"] is None else str(ar["score"])
        st = "checked" if ar["status"] == "checked" else ar["status"]
        L.append(f"| {ar['title']} | {sc} | {grade(ar['score'])} | {len(ar['findings'])} | {st} |")
    top = sorted(a.findings, key=lambda f: (-ORDER[f["severity"]], -AREAS[f["area"]][1]))[:15]
    if top:
        L += ["", "## Fix first", ""]
        for i, f in enumerate(top, 1):
            L.append(f"{i}. **[{f['severity'].upper()}] {AREAS[f['area']][0]}** - {f['problem']} (`{f['where']}`)  \n"
                     f"   fix: {f['fix']}")
    L += ["", "## Details"]
    for key, ar in res["areas"].items():
        if not ar["findings"] and not a.notes.get(key):
            continue
        L += ["", f"### {ar['title']}" + (f" - {ar['score']}/100" if ar["score"] is not None else f" - {ar['status']}")]
        for f in sorted(ar["findings"], key=lambda f: -ORDER[f["severity"]])[:40]:
            L.append(f"- [{f['severity']}] `{f['where']}`: {f['problem']} -> {f['fix']}")
        if len(ar["findings"]) > 40:
            L.append(f"- ... {len(ar['findings']) - 40} more (--json)")
        for n in a.notes.get(key, []):
            L.append(f"- note: {n}")
    unchecked = [f"{ar['title']}: {ar['status'][len('not checked: '):]}" for ar in res["areas"].values()
                 if ar["status"].startswith("not checked")]
    if unchecked:
        L += ["", "## Not checked (not counted as passed)"] + [f"- {u}" for u in unchecked]
    na = [ar["title"] for ar in res["areas"].values() if ar["status"] == "n/a"]
    if na:
        L += ["", "Not applicable to this project type: " + ", ".join(na)]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--quick", action="store_true", help="static checks only; do not run build/tests")
    ap.add_argument("--offline", action="store_true", help="skip live dependency checks")
    ap.add_argument("--deep", action="store_true", help="also run the clean-room portability proof")
    ap.add_argument("--only", help="comma list of areas: " + ",".join(AREAS))
    ap.add_argument("--out", type=Path, help="also write the markdown report here")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    repo = Path(args.repo).resolve()
    a = Audit(repo, args)
    only = set(args.only.split(",")) if args.only else set(AREAS)
    for key in AREAS:
        if key in only:
            getattr(a, "area_" + key.replace("-", "_"))()
        else:
            a.status[key] = "not checked: excluded by --only"
    res = a.score()
    if args.json:
        print(json.dumps({"repo": str(repo), "types": sorted(a.types), **{k: v for k, v in res.items() if k != "areas"}, "areas": res["areas"],
                          "notes": a.notes}, indent=2, ensure_ascii=False))
    else:
        report = render(a, res)
        print(report)
        if args.out:
            args.out.write_text(report, encoding="utf-8")
    return 1 if res["verdict"] == "NOT READY" else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
