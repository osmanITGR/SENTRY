#!/usr/bin/env python3
"""Find what makes a project work on this machine but not on someone else's.

Usage:
  python3 portability_audit.py [REPO] [--json] [--min-severity low|medium|high]

Checks (each finding has a severity and a concrete fix):
  toolchain    language/runtime/package-manager versions not pinned
  lockfile     lockfile missing, untracked, or out of sync with the manifest
  undeclared   imports / script binaries not declared as dependencies
               (work here only because they are installed globally or transitively)
  local-only   files the code references that exist here but are not in git
  abs-path     machine-specific absolute paths (for example /home/me, C:\\Users\\me)
  case         imports whose letter case differs from the real file name
               (fine on Windows/macOS, broken on Linux)
  env          environment variables used but documented nowhere
  line-endings CRLF in shell scripts, missing .gitattributes
  exec-bit     scripts/wrappers committed without the executable bit
  encoding     Python text I/O without encoding= (differs on Windows)

Exit 1 when any HIGH finding exists. Standard library only (Python 3.11+).
"""
# audit: allow-file - this file defines detection patterns; scanning it would flag the rules themselves
from __future__ import annotations

import argparse
import ast
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
DETECT_CANDIDATES = [HERE / "detect_stack.py",
                     HERE.parent.parent / "codebase-recon" / "scripts" / "detect_stack.py"]
SEV = {"high": 3, "medium": 2, "low": 1}
NODE_BUILTINS = set("""assert async_hooks buffer child_process cluster console constants crypto dgram
diagnostics_channel dns domain events fs http http2 https inspector module net os path perf_hooks process
punycode querystring readline repl stream string_decoder sys timers tls trace_events tty url util v8 vm
wasi worker_threads zlib test sea sqlite""".split())
BIN_PACKAGE = {"tsc": "typescript", "tsx": "tsx", "ts-node": "ts-node", "eslint": "eslint", "prettier": "prettier",
               "jest": "jest", "vitest": "vitest", "vite": "vite", "next": "next", "nuxt": "nuxt",
               "webpack": "webpack-cli", "rollup": "rollup", "esbuild": "esbuild", "nodemon": "nodemon",
               "playwright": "@playwright/test", "cross-env": "cross-env", "rimraf": "rimraf",
               "concurrently": "concurrently", "mocha": "mocha", "ava": "ava", "electron": "electron",
               "electron-builder": "electron-builder", "react-scripts": "react-scripts", "astro": "astro",
               "svelte-kit": "@sveltejs/kit", "ng": "@angular/cli", "expo": "expo", "turbo": "turbo",
               "nx": "nx", "biome": "@biomejs/biome", "stylelint": "stylelint", "husky": "husky",
               "lint-staged": "lint-staged", "tailwindcss": "tailwindcss", "prisma": "prisma",
               "drizzle-kit": "drizzle-kit", "storybook": "storybook", "cypress": "cypress"}
SHELL_BUILTINS = {"node", "npm", "npx", "pnpm", "yarn", "bun", "cd", "echo", "rm", "cp", "mv", "mkdir", "cat",
                  "git", "exit", "test", "true", "false", "set", "export", "sh", "bash", "python", "python3",
                  "pip", "docker", "make", "env", "sleep", "if", "then", "fi", "for", "do", "done", "chmod",
                  "touch", "ls", "find", "grep", "sed", "awk", "curl", "wget", "tar", "unzip", "open", "start"}
PY_IMPORT_TO_DIST = {"yaml": "pyyaml", "cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn",
                     "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "jwt": "pyjwt", "dateutil": "python-dateutil",
                     "serial": "pyserial", "usb": "pyusb", "Crypto": "pycryptodome", "attr": "attrs",
                     "magic": "python-magic", "docx": "python-docx", "pptx": "python-pptx", "fitz": "pymupdf",
                     "google.protobuf": "protobuf", "skimage": "scikit-image", "OpenSSL": "pyopenssl",
                     "MySQLdb": "mysqlclient", "psycopg2": "psycopg2-binary", "win32api": "pywin32",
                     "gi": "pygobject", "zmq": "pyzmq", "telegram": "python-telegram-bot", "socketio": "python-socketio",
                     "engineio": "python-engineio", "multipart": "python-multipart", "jose": "python-jose",
                     "slugify": "python-slugify", "Levenshtein": "python-levenshtein", "kafka": "kafka-python",
                     "github": "pygithub", "git": "gitpython", "markdown": "markdown", "ruamel": "ruamel.yaml"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "dist", "build", "target", "vendor", ".dart_tool",
             ".gradle", "__pycache__", "out", "bin", "obj", ".next", ".nuxt", "coverage", ".tox", "site-packages"}
ENV_IGNORE = {"PATH", "HOME", "USER", "USERNAME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "TMPDIR",
              "PWD", "SHELL", "LANG", "LC_ALL", "TERM", "CI", "NODE_ENV", "GITHUB_ACTIONS", "PYTHONPATH",
              "VIRTUAL_ENV", "HOSTNAME", "COMPUTERNAME", "OS", "PROGRAMFILES", "SYSTEMROOT", "XDG_CONFIG_HOME",
              "XDG_DATA_HOME", "XDG_CACHE_HOME", "JAVA_HOME", "ANDROID_HOME", "ANDROID_SDK_ROOT", "GOPATH"}
ENV_RES = [r"process\.env\.([A-Z][A-Z0-9_]+)", r"process\.env\[['\"]([A-Z][A-Z0-9_]+)['\"]\]",
           r"import\.meta\.env\.([A-Z][A-Z0-9_]+)", r"os\.environ\[['\"]([A-Z][A-Z0-9_]+)['\"]\]",
           r"os\.(?:environ\.get|getenv)\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]", r"os\.Getenv\(\"([A-Z][A-Z0-9_]+)\"\)",
           r"(?:std::)?env::var\(\"([A-Z][A-Z0-9_]+)\"\)", r"System\.getenv\(\"([A-Z][A-Z0-9_]+)\"\)",
           r"Environment\.GetEnvironmentVariable\(\"([A-Z][A-Z0-9_]+)\"\)",
           r"Platform\.environment\[['\"]([A-Z][A-Z0-9_]+)['\"]\]", r"ENV\[['\"]([A-Z][A-Z0-9_]+)['\"]\]",
           r"String\.fromEnvironment\(['\"]([A-Z][A-Z0-9_]+)['\"]"]
ABS_PATH_RE = re.compile(r"(?<![\w/])(/home/[a-z_][\w.-]*/|/Users/[A-Za-z][\w.-]*/|[A-Za-z]:\\\\?Users\\\\?[\w. -]+)")
FILE_REF_RE = re.compile(r"['\"]((?:\.{1,2}/)?[\w@.-]+(?:/[\w@.-]+)*\.(?:json|ya?ml|toml|ini|cfg|conf|env|txt|csv|"
                         r"db|sqlite3?|pem|crt|key|p12|jks|keystore|png|jpe?g|gif|svg|ico|wav|mp3|mp4|onnx|tflite|"
                         r"pt|pth|h5|pkl|bin|ttf|otf|woff2?|xml|html|properties))['\"]")
ALLOW_RE = re.compile(r"portability:\s*allow", re.I)  # reviewed exception on that line
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".go", ".rs", ".java", ".kt",
            ".cs", ".dart", ".swift", ".c", ".h", ".cpp", ".hpp", ".ino", ".php", ".rb", ".sh", ".gradle", ".kts"}


def call_args(text: str, start: int) -> str:
    """Argument text of a call whose '(' ends at `start`, with nested brackets balanced."""
    depth, i = 1, start
    while i < len(text) and depth:
        depth += text[i] in "([{"
        depth -= text[i] in ")]}"
        i += 1
    return text[start:i - 1]


class Audit:
    def __init__(self, repo: Path):
        self.repo = repo
        self.findings: list[dict] = []
        out = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True)
        self.is_git = out.returncode == 0
        self.tracked = set(out.stdout.decode(errors="replace").split("\0")) - {""} if self.is_git else set()
        out = subprocess.run(["git", "ls-files", "-s"], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.modes = {l.split("\t", 1)[1]: l.split()[0] for l in out.stdout.splitlines() if "\t" in l}

    # ---------------------------------------------------------- helpers
    def add(self, sev: str, kind: str, where: str, problem: str, fix: str) -> None:
        self.findings.append({"severity": sev, "kind": kind, "where": where, "problem": problem, "fix": fix})

    def read(self, rel: str) -> str:
        try:
            return (self.repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def rel(self, root: str, name: str) -> str:
        return name if root == "." else f"{root}/{name}"

    def exists(self, rel: str) -> bool:
        return (self.repo / rel).exists()

    def tracked_or_missing(self, rel: str) -> str:
        if not self.exists(rel):
            return "missing"
        return "tracked" if (rel in self.tracked or not self.is_git) else "untracked"

    def code_files(self) -> list[str]:
        files = sorted(self.tracked) if self.is_git else [
            str(p.relative_to(self.repo)) for p in self.repo.rglob("*") if p.is_file()]
        return [f for f in files if Path(f).suffix in CODE_EXT and not set(Path(f).parts) & SKIP_DIRS]

    # ---------------------------------------------------------- checks
    def toolchain_and_locks(self, projects: list[dict]) -> None:
        def any_file(root, *names):
            return next((n for n in names if self.exists(self.rel(root, n)) or self.exists(n)), None)

        for p in projects:
            root, stack, pm = p["root"], p["stack"], p["package_manager"]
            where = f"{root} ({stack})"
            if stack == "node":
                pkg = json.loads(self.read(self.rel(root, "package.json")) or "{}")
                pinned = any_file(root, ".nvmrc", ".node-version", ".tool-versions", "mise.toml", ".mise.toml") \
                    or (pkg.get("engines") or {}).get("node") or (pkg.get("volta") or {}).get("node")
                if not pinned:
                    self.add("medium", "toolchain", where, "Node.js version is not pinned",
                             "add .nvmrc with the version you use (`node -v > .nvmrc`) and \"engines\": {\"node\": \">=X\"}")
                if pm != "npm" and not pkg.get("packageManager"):
                    self.add("medium", "toolchain", where, f"{pm} version is not pinned",
                             f"add \"packageManager\": \"{pm}@<version>\" to package.json (Corepack enforces it)")
                lock = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock",
                        "bun": "bun.lock"}[pm]
                state = self.tracked_or_missing(self.rel(root, lock))
                if pm == "bun" and state == "missing":
                    state = self.tracked_or_missing(self.rel(root, "bun.lockb"))
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if deps and state != "tracked":
                    self.add("high", "lockfile", where, f"{lock} is {state}: others resolve different versions",
                             f"run `{pm} install` and commit {lock}; install with `{p['commands'].get('install', pm + ' install')}`")
                elif state == "tracked" and lock == "package-lock.json":
                    try:
                        root_entry = json.loads(self.read(self.rel(root, lock))).get("packages", {}).get("", {})
                        locked = {**root_entry.get("dependencies", {}), **root_entry.get("devDependencies", {})}
                        drift = sorted(n for n, spec in deps.items() if locked.get(n) != spec)
                        if drift:
                            self.add("high", "lockfile", where,
                                     f"package-lock.json out of sync with package.json: {', '.join(drift[:8])}",
                                     "run `npm install` and commit the updated lockfile (`npm ci` fails otherwise)")
                    except json.JSONDecodeError:
                        self.add("high", "lockfile", where, "package-lock.json is not valid JSON", "regenerate it")
            elif stack == "python":
                py = tomllib.loads(self.read(self.rel(root, "pyproject.toml")) or "") if tomllib else {}
                if not (any_file(root, ".python-version", ".tool-versions", "runtime.txt", "mise.toml")
                        or py.get("project", {}).get("requires-python")
                        or (py.get("tool", {}).get("poetry", {}).get("dependencies") or {}).get("python")):
                    self.add("medium", "toolchain", where, "Python version is not pinned",
                             "add .python-version (e.g. `3.12`) and requires-python in pyproject.toml")
                locks = [l for l in ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock")
                         if self.exists(self.rel(root, l))]
                for l in locks:
                    if self.tracked_or_missing(self.rel(root, l)) != "tracked":
                        self.add("high", "lockfile", where, f"{l} exists but is not committed", f"commit {l}")
                reqs = [r for r in Path(self.repo / root).glob("requirements*.txt")]
                if not locks and reqs:
                    loose = [l.strip() for r in reqs for l in r.read_text(errors="replace", encoding="utf-8").splitlines()
                             if l.strip() and not l.strip().startswith(("#", "-")) and "==" not in l and "@" not in l]
                    if loose:
                        self.add("medium", "lockfile", where,
                                 f"{len(loose)} requirement(s) not pinned (e.g. {', '.join(loose[:4])})",
                                 "pin exact versions (`pip freeze > requirements.lock` / pip-compile) or use uv.lock")
                if not locks and not reqs and (py.get("project", {}).get("dependencies") or
                                               py.get("tool", {}).get("poetry")):
                    self.add("medium", "lockfile", where, "dependencies declared but no lockfile",
                             "use `uv lock` (or poetry lock) and commit the lockfile")
            elif stack == "go":
                gomod = self.read(self.rel(root, "go.mod"))
                if "require" in gomod and self.tracked_or_missing(self.rel(root, "go.sum")) != "tracked":
                    self.add("high", "lockfile", where, "go.sum is missing or not committed",
                             "run `go mod tidy` and commit go.sum")
            elif stack == "rust":
                is_app = self.exists(self.rel(root, "src/main.rs")) or "[[bin]]" in self.read(self.rel(root, "Cargo.toml"))
                if is_app and self.tracked_or_missing(self.rel(root, "Cargo.lock")) != "tracked":
                    self.add("high", "lockfile", where, "Cargo.lock not committed for an application",
                             "commit Cargo.lock (applications must, libraries may)")
                if not any_file(root, "rust-toolchain.toml", "rust-toolchain"):
                    self.add("low", "toolchain", where, "Rust toolchain not pinned",
                             "add rust-toolchain.toml with channel = \"<version>\"")
            elif stack in ("flutter", "dart"):
                if self.tracked_or_missing(self.rel(root, "pubspec.lock")) != "tracked" and stack == "flutter":
                    self.add("high", "lockfile", where, "pubspec.lock not committed for an app",
                             "commit pubspec.lock")
                if stack == "flutter" and not any_file(root, ".fvmrc", ".fvm/fvm_config.json") and \
                        not re.search(r"^\s+flutter:\s*['\"]?[\d>=^]", self.read(self.rel(root, "pubspec.yaml")), re.M):
                    self.add("medium", "toolchain", where, "Flutter SDK version not pinned",
                             "add environment: flutter: \">=X.Y.Z\" in pubspec.yaml or pin with FVM (.fvmrc)")
            elif stack == "dotnet":
                if not any_file(root, "global.json"):
                    self.add("medium", "toolchain", where, ".NET SDK not pinned",
                             "add global.json (`dotnet new globaljson --sdk-version <ver>`)")
            elif stack in ("android-gradle", "gradle"):
                if not self.exists(self.rel(root, "gradlew")):
                    self.add("high", "toolchain", where, "no Gradle wrapper: everyone builds with their own Gradle",
                             "run `gradle wrapper` and commit gradlew, gradlew.bat and gradle/wrapper/*")
                gtext = "".join(self.read(str(f.relative_to(self.repo))) for f in (self.repo / root).glob("**/build.gradle*")
                                if not set(f.parts) & SKIP_DIRS)
                if "toolchain" not in gtext.lower():
                    self.add("low", "toolchain", where, "JDK version not pinned",
                             "add kotlin { jvmToolchain(17) } / java { toolchain { languageVersion = JavaLanguageVersion.of(17) } }")
            elif stack == "maven":
                if not self.exists(self.rel(root, "mvnw")):
                    self.add("medium", "toolchain", where, "no Maven wrapper", "run `mvn wrapper:wrapper` and commit it")
            elif stack == "platformio":
                ini = self.read(self.rel(root, "platformio.ini"))
                for m in re.finditer(r"^\s*platform\s*=\s*(\S+)", ini, re.M):
                    if "@" not in m.group(1) and "#" not in m.group(1):
                        self.add("medium", "toolchain", where, f"PlatformIO platform `{m.group(1)}` not pinned",
                                 f"pin it, e.g. platform = {m.group(1)}@<version>")
                if re.search(r"^\s*lib_deps\s*=", ini, re.M) and re.search(r"^\s+[\w/-]+\s*$", ini, re.M):
                    self.add("medium", "toolchain", where, "lib_deps without versions",
                             "pin libraries: owner/lib@^1.2.3")
            elif stack == "arduino":
                if not any_file(root, "sketch.yaml"):
                    self.add("medium", "toolchain", where, "board core and libraries not pinned",
                             "add sketch.yaml with a profile (fqbn, platform version, libraries) for arduino-cli")

    def node_undeclared(self, projects: list[dict]) -> None:
        workspace_names = set()
        for f in self.tracked or set():
            if f.endswith("package.json") and "node_modules" not in f:
                try:
                    workspace_names.add(json.loads(self.read(f)).get("name", ""))
                except json.JSONDecodeError:
                    pass
        for p in [p for p in projects if p["stack"] == "node"]:
            root = p["root"]
            pkg = json.loads(self.read(self.rel(root, "package.json")) or "{}")
            declared = set()
            for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                declared |= set(pkg.get(k, {}))
            aliases = set()
            for cfg in ("tsconfig.json", "jsconfig.json"):
                try:
                    text = re.sub(r"//.*|/\*.*?\*/", "", self.read(self.rel(root, cfg)), flags=re.S)
                    aliases |= {k.split("/")[0].rstrip("*") for k in
                                json.loads(text or "{}").get("compilerOptions", {}).get("paths", {})}
                except json.JSONDecodeError:
                    pass
            missing: dict[str, str] = {}
            for f in self.code_files():
                if not (root == "." or f.startswith(root + "/")) or Path(f).suffix not in (
                        ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"):
                    continue
                text = self.read(f)
                for spec in re.findall(r"(?:from\s+|import\s+|require\(\s*|import\(\s*)['\"]([^'\"./][^'\"]*)['\"]", text):
                    if spec.startswith(("node:", "#", "~", "virtual:", "data:", "http")) or spec.startswith("@/"):
                        continue
                    name = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
                    if name in NODE_BUILTINS or name in declared or name in workspace_names or \
                            name in aliases or name.split("/")[0] in aliases or f"@types/{name}" in declared:
                        continue
                    missing.setdefault(name, f)
            for name, f in sorted(missing.items()):
                self.add("high", "undeclared", f, f"imports `{name}` but it is not in {self.rel(root, 'package.json')}",
                         f"`{p['package_manager']} add {name}` (works here only via a global/transitive install)")
            for script, cmd in (pkg.get("scripts") or {}).items():
                for part in re.split(r"&&|\|\||;|\|", cmd):
                    toks = [t for t in part.strip().split() if "=" not in t or t.startswith("-")]
                    if not toks:
                        continue
                    tok = toks[1] if toks[0] in ("npx", "pnpx", "bunx") and len(toks) > 1 else toks[0]
                    if tok in SHELL_BUILTINS or tok.startswith((".", "/", "$")):
                        continue
                    need = BIN_PACKAGE.get(tok, tok)
                    if tok in BIN_PACKAGE and need not in declared and tok not in declared:
                        self.add("high", "undeclared", f"{self.rel(root, 'package.json')} scripts.{script}",
                                 f"runs `{tok}` but `{need}` is not a dependency (works here via a global install)",
                                 f"`{p['package_manager']} add -D {need}`")

    def python_undeclared(self, projects: list[dict]) -> None:
        stdlib = set(sys.stdlib_module_names) | {"__future__"}
        for p in [p for p in projects if p["stack"] == "python"]:
            root = p["root"]
            base = self.repo / root
            declared, locked = set(), set()
            norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()
            py = tomllib.loads(self.read(self.rel(root, "pyproject.toml")) or "") if tomllib else {}
            reqs = list(py.get("project", {}).get("dependencies", []))
            for g in (py.get("project", {}).get("optional-dependencies") or {}).values():
                reqs += g
            for g in (py.get("dependency-groups") or {}).values():
                reqs += [x for x in g if isinstance(x, str)]
            for section in ("dependencies", "dev-dependencies"):
                reqs += list((py.get("tool", {}).get("poetry", {}).get(section) or {}).keys())
            for g in (py.get("tool", {}).get("poetry", {}).get("group") or {}).values():
                reqs += list((g.get("dependencies") or {}).keys())
            for r in base.glob("requirements*.txt"):
                reqs += [l for l in r.read_text(errors="replace", encoding="utf-8").splitlines() if l.strip() and not l.startswith(("#", "-"))]
            reqs += re.findall(r"^\s+([A-Za-z][\w.-]*)", (re.search(r"install_requires\s*=(.*?)(?:\n\S|\Z)",
                                                                     self.read(self.rel(root, "setup.cfg")), re.S) or [None, ""])[1], re.M)
            for r in reqs:
                m = re.match(r"\s*([A-Za-z0-9][\w.-]*)", r)
                if m:
                    declared.add(norm(m.group(1)))
            for lock in ("uv.lock", "poetry.lock", "pdm.lock"):
                if tomllib and self.exists(self.rel(root, lock)):
                    locked |= {norm(x.get("name", "")) for x in tomllib.loads(self.read(self.rel(root, lock))).get("package", [])}
            local = {f.stem for f in base.rglob("*.py") if not set(f.parts) & SKIP_DIRS} | \
                    {d.name for d in base.rglob("*") if d.is_dir() and (d / "__init__.py").exists()} | \
                    {d.name for d in base.iterdir() if d.is_dir()} | ({d.name for d in (base / "src").iterdir()}
                                                                    if (base / "src").is_dir() else set())
            seen: dict[str, str] = {}
            for f in self.code_files():
                if not f.endswith(".py") or not (root == "." or f.startswith(root + "/")):
                    continue
                try:
                    tree = ast.parse(self.read(f))
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        names = [node.module]
                    for n in names:
                        top = n.split(".")[0]
                        if top in stdlib or top in local or top.startswith("_"):
                            continue
                        dist = PY_IMPORT_TO_DIST.get(n.split(".")[0] + ("." + n.split(".")[1] if "." in n else ""),
                                                     PY_IMPORT_TO_DIST.get(top, top))
                        if norm(dist) in declared or norm(top) in declared:
                            continue
                        seen.setdefault(dist, f)
            if not declared and not seen:
                continue
            for dist, f in sorted(seen.items()):
                if norm(dist) in locked:
                    self.add("medium", "undeclared", f, f"imports `{dist}` which is only a transitive dependency",
                             f"declare it directly (`uv add {dist}` / add to requirements) - a dependency update can drop it")
                else:
                    self.add("high", "undeclared", f, f"imports `{dist}` but it is not declared anywhere",
                             f"add `{dist}` to pyproject/requirements (works here because it is installed globally)")

    def files_and_text(self) -> None:
        env_used: dict[str, str] = {}
        for f in self.code_files():
            text = self.read(f)
            fdir = str(Path(f).parent)
            for i, line in enumerate(text.splitlines(), 1):
                m = ABS_PATH_RE.search(line)
                if m and "example" not in line.lower() and not ALLOW_RE.search(line):
                    self.add("high", "abs-path", f"{f}:{i}", f"machine-specific path `{m.group(1)}`",
                             "use a path relative to the project (e.g. Path(__file__).parent / ...), "
                             "a config/env value, or the platform's app-data API")
            for m in FILE_REF_RE.finditer(text):
                ref = m.group(1)
                for cand in ([str(Path(fdir) / ref)] if ref.startswith(".") else [str(Path(fdir) / ref), ref]):
                    cand = os.path.normpath(cand).replace("\\", "/")
                    if self.exists(cand) and cand not in self.tracked and self.is_git and \
                            not (self.repo / cand).is_dir():
                        line_no = text[:m.start()].count("\n") + 1
                        self.add("high", "local-only", f"{f}:{line_no}",
                                 f"uses `{cand}` which exists only on this machine (not in git)",
                                 "commit it; if it is secret/machine config, commit an example copy "
                                 "(e.g. config.example.json), document how to create it, and fail with a clear message when absent")
                        break
            if Path(f).suffix in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".vue", ".svelte"):
                for m in re.finditer(r"(?:from\s+|import\s+|require\(\s*|import\(\s*)['\"](\.{1,2}/[^'\"]+)['\"]", text):
                    self.case_check(f, m.group(1), text[:m.start()].count("\n") + 1)
            lines_all = text.splitlines()
            for rx in ENV_RES:
                for m in re.finditer(rx, text):
                    name = m.group(1)
                    line_txt = lines_all[text[:m.start()].count("\n")] if lines_all else ""
                    if name not in ENV_IGNORE and not ALLOW_RE.search(line_txt):
                        env_used.setdefault(name, f)
            if f.endswith(".py"):
                lines_ = text.splitlines()
                allowed = lambda pos: ALLOW_RE.search(lines_[text[:pos].count("\n")] if lines_ else "")
                for m in re.finditer(r"(?<![\w.])open\(|\.(read_text|write_text)\(", text):
                    args = call_args(text, m.end())
                    if allowed(m.start()) or "encoding" in args:
                        continue
                    line_no = text[:m.start()].count("\n") + 1
                    if m.group(1):
                        self.add("low", "encoding", f"{f}:{line_no}", f"{m.group(1)}() without encoding=",
                                 "pass encoding=\"utf-8\"")
                    elif args.strip() and not re.search(r"['\"][rwax+]*b[rwax+]*['\"]", args):
                        self.add("low", "encoding", f"{f}:{line_no}",
                                 "text file opened without encoding= (Windows defaults to a legacy code page)",
                                 "pass encoding=\"utf-8\"")
        docs = ""
        for f in sorted(self.tracked):
            name = Path(f).name.lower()
            if name.startswith((".env.example", ".env.sample", ".env.template", ".env.dist", "readme")) or \
                    f.startswith("docs/") or name.startswith(("docker-compose", "compose.")) or "/workflows/" in f \
                    or name in ("app.json", "fly.toml", "render.yaml", "netlify.toml", "vercel.json", "wrangler.toml"):
                docs += self.read(f) + "\n"
        for name, f in sorted(env_used.items()):
            if not re.search(rf"\b{re.escape(name)}\b", docs):
                self.add("medium", "env", f, f"environment variable `{name}` is used but documented nowhere",
                         f"add `{name}=` to .env.example (and the README) with a description")

    def case_check(self, src: str, spec: str, line: int) -> None:
        base = (self.repo / src).parent / spec
        exts = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".svelte", "/index.ts", "/index.tsx", "/index.js"]
        if any(Path(str(base) + e).exists() and self._exact_case(Path(str(base) + e)) for e in exts):
            return
        for e in exts:
            target = Path(str(base) + e)
            match = self._case_insensitive(target)
            if match:
                self.add("high", "case", f"{src}:{line}",
                         f"import `{spec}` matches `{match.relative_to(self.repo)}` only case-insensitively",
                         "fix the import's letter case (Linux file systems are case-sensitive)")
                return

    def _exact_case(self, p: Path) -> bool:
        try:
            rel = p.resolve().relative_to(self.repo.resolve())
        except ValueError:
            return True
        cur = self.repo
        for part in rel.parts:
            try:
                names = {c.name for c in cur.iterdir()}
            except OSError:
                return False
            if part not in names:
                return False
            cur = cur / part
        return True

    def _case_insensitive(self, p: Path) -> Path | None:
        try:
            rel = Path(str(p)).resolve().relative_to(self.repo.resolve())
        except ValueError:
            return None
        cur = self.repo
        for part in rel.parts:
            try:
                hit = next((c for c in cur.iterdir() if c.name.lower() == part.lower()), None)
            except OSError:
                return None
            if hit is None:
                return None
            cur = hit
        return cur if cur.is_file() else None

    def scripts_and_endings(self) -> None:
        scripts = [f for f in self.tracked if f.endswith((".sh", ".bash")) or Path(f).name in ("gradlew", "mvnw")]
        for f in sorted(self.tracked):
            if f in scripts or Path(f).suffix in CODE_EXT | {""}:
                try:
                    head = (self.repo / f).read_bytes()[:200]
                except OSError:
                    continue
                if head.startswith(b"#!") and f not in scripts:
                    scripts.append(f)
        for f in sorted(scripts):
            try:
                data = (self.repo / f).read_bytes()
            except OSError:
                continue
            if b"\r\n" in data:
                self.add("high", "line-endings", f, "shell script has CRLF line endings (`bad interpreter` on Linux/macOS)",
                         "convert to LF and add `*.sh text eol=lf` (and gradlew/mvnw) to .gitattributes")
            if self.modes.get(f) == "100644":
                self.add("medium", "exec-bit", f, "committed without the executable bit (`permission denied` elsewhere)",
                         f"git update-index --chmod=+x {f}")
        if not self.exists(".gitattributes") and (scripts or any(f.endswith((".bat", ".cmd", ".ps1")) for f in self.tracked)):
            self.add("medium", "line-endings", ".gitattributes",
                     "no .gitattributes: Windows checkouts may convert scripts to CRLF",
                     "add .gitattributes:  * text=auto  |  *.sh text eol=lf  |  gradlew text eol=lf  |  *.bat text eol=crlf  |  *.cmd text eol=crlf")


def load_detect():
    path = next((p for p in DETECT_CANDIDATES if p.exists()), None)
    if path is None:
        sys.exit("detect_stack.py not found: install the codebase-recon skill alongside this one.")
    spec = importlib.util.spec_from_file_location("detect_stack", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["detect_stack"] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-severity", choices=list(SEV), default="low")
    args = ap.parse_args()
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)  # `| head` must not crash the report
    repo = Path(args.repo).resolve()
    projects = load_detect().detect(repo)["projects"]
    a = Audit(repo)
    a.toolchain_and_locks(projects)
    a.node_undeclared(projects)
    a.python_undeclared(projects)
    a.files_and_text()
    a.scripts_and_endings()
    findings = sorted((f for f in a.findings if SEV[f["severity"]] >= SEV[args.min_severity]),
                      key=lambda f: (-SEV[f["severity"]], f["kind"], f["where"]))
    if args.json:
        print(json.dumps({"repo": str(repo), "findings": findings}, indent=2))
    else:
        print(f"Portability audit of {repo}: {len(projects)} project(s), {len(findings)} finding(s)")
        if not a.is_git:
            print("WARNING: not a git repository; cannot tell what others actually receive.")
        for sev in ("high", "medium", "low"):
            group = [f for f in findings if f["severity"] == sev]
            if group:
                print(f"\n## {sev.upper()} ({len(group)})")
                for f in group[:60]:
                    print(f"  [{f['kind']}] {f['where']}: {f['problem']}\n      fix: {f['fix']}")
                if len(group) > 60:
                    print(f"  ... {len(group) - 60} more (--json for all)")
        if not findings:
            print("No portability issues found by static checks. Prove it with clean_room.py.")
    return 1 if any(f["severity"] == "high" for f in findings) else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
