#!/usr/bin/env python3
"""Detect every project in a repository and the exact commands to check it.

Usage:
  python3 detect_stack.py [REPO_ROOT] [--json] [--max-depth N]

Prints, for each project root found (monorepos supported), the stack, the
package manager, and the install/lint/typecheck/build/test commands that the
project itself defines. Project-defined scripts always win over generic
fallbacks, so the commands match what CI and the maintainers actually run.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist",
    "build", "out", "target", "vendor", ".gradle", ".dart_tool", ".idea",
    ".next", ".nuxt", ".turbo", ".cache", "coverage", "bin", "obj", ".pio",
    "Pods", ".expo", ".svelte-kit", "site-packages",
}
PYTHON = "python" if os.name == "nt" else "python3"
CHECK_ORDER = ["install", "format", "lint", "typecheck", "build", "test"]


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def has(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def node_project(root: Path) -> dict | None:
    pkg_file = root / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        pkg = json.loads(read(pkg_file) or "{}")
    except json.JSONDecodeError:
        pkg = {}
    scripts = pkg.get("scripts", {}) or {}
    if (root / "pnpm-lock.yaml").exists():
        pm = "pnpm"
    elif (root / "yarn.lock").exists():
        pm = "yarn"
    elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        pm = "bun"
    else:
        pm = "npm"
    run = {"npm": "npm run", "pnpm": "pnpm run", "yarn": "yarn", "bun": "bun run"}[pm]
    install = {"npm": "npm ci" if (root / "package-lock.json").exists() else "npm install",
               "pnpm": "pnpm install --frozen-lockfile", "yarn": "yarn install --frozen-lockfile",
               "bun": "bun install"}[pm]

    def script(*names: str) -> str | None:
        for name in names:
            if name in scripts:
                return f"{run} {name}"
        return None

    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    cmds = {"install": install}
    cmds["format"] = script("format:check", "fmt:check", "prettier:check")
    cmds["lint"] = script("lint", "eslint")
    cmds["typecheck"] = script("typecheck", "type-check", "tsc", "check-types", "types")
    if not cmds["typecheck"] and (root / "tsconfig.json").exists():
        cmds["typecheck"] = "npx --no-install tsc --noEmit"
    cmds["build"] = script("build", "compile")
    test = scripts.get("test", "")
    if test and "no test specified" not in test:
        cmds["test"] = f"{run} test" if pm != "npm" else "npm test"
    else:
        cmds["test"] = script("test:unit", "vitest", "jest")
    frameworks = [f for f in ("react", "next", "vue", "svelte", "electron", "react-native",
                              "expo", "express", "fastify", "nestjs", "@nestjs/core",
                              "vite", "vitest", "jest", "playwright", "@playwright/test",
                              "typescript") if f in deps]
    tool = {"npm": "npm", "pnpm": "pnpm", "yarn": "yarn", "bun": "bun"}[pm]
    return {"stack": "node", "package_manager": pm, "frameworks": frameworks,
            "commands": cmds, "required_tools": [tool]}


def python_project(root: Path) -> dict | None:
    markers = ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile"]
    if not any((root / m).exists() for m in markers):
        return None
    pyproject = read(root / "pyproject.toml")
    if (root / "uv.lock").exists():
        pm, prefix, install = "uv", "uv run ", "uv sync"
    elif (root / "poetry.lock").exists() or "[tool.poetry]" in pyproject:
        pm, prefix, install = "poetry", "poetry run ", "poetry install"
    elif (root / "pdm.lock").exists():
        pm, prefix, install = "pdm", "pdm run ", "pdm install"
    elif (root / "Pipfile").exists():
        pm, prefix, install = "pipenv", "pipenv run ", "pipenv install --dev"
    else:
        venv_py = next((f"{v}/{b}" for v in (".venv", "venv")
                        for b in ("bin/python", "Scripts/python.exe") if (root / v / b).exists()), None)
        pm, prefix = "pip", (f"{venv_py} -m " if venv_py else f"{PYTHON} -m ")
        install = ("pip install -r requirements.txt" if (root / "requirements.txt").exists()
                   else "pip install -e .")
    cfg = pyproject + read(root / "setup.cfg") + read(root / "tox.ini")
    cmds = {"install": install}
    if "[tool.ruff" in cfg or (root / "ruff.toml").exists() or (root / ".ruff.toml").exists():
        cmds["lint"] = f"{prefix}ruff check ."
        cmds["format"] = f"{prefix}ruff format --check ."
    elif "[tool.black" in cfg:
        cmds["format"] = f"{prefix}black --check ."
    if "lint" not in cmds and ("[flake8]" in cfg or (root / ".flake8").exists()):
        cmds["lint"] = f"{prefix}flake8"
    if "[tool.mypy" in cfg or "[mypy" in cfg or (root / "mypy.ini").exists():
        cmds["typecheck"] = f"{prefix}mypy ."
    elif "[tool.pyright" in cfg or (root / "pyrightconfig.json").exists():
        cmds["typecheck"] = f"{prefix}pyright"
    has_tests = any((root / d).is_dir() for d in ("tests", "test")) or any(root.glob("test_*.py"))
    if "[tool.pytest" in cfg or "[pytest]" in cfg or (root / "pytest.ini").exists() or (
            has_tests and "pytest" in (cfg + read(root / "requirements-dev.txt")
                                       + read(root / "requirements.txt"))):
        cmds["test"] = f"{prefix}pytest -q"
    elif has_tests:
        cmds["test"] = (f"{prefix}unittest discover -q" if pm == "pip"
                         else f"{prefix}python -m unittest discover -q")
    return {"stack": "python", "package_manager": pm, "frameworks": [],
            "commands": cmds, "required_tools": [PYTHON] + ([pm] if pm != "pip" else [])}


def simple(root: Path, marker: str, stack: str, cmds: dict, tools: list[str]) -> dict | None:
    if not (root / marker).exists():
        return None
    return {"stack": stack, "package_manager": tools[0], "frameworks": [],
            "commands": cmds, "required_tools": tools}


def go_project(root: Path) -> dict | None:
    lint = "golangci-lint run" if any((root / f).exists() for f in (
        ".golangci.yml", ".golangci.yaml", ".golangci.toml")) else "go vet ./..."
    return simple(root, "go.mod", "go", {
        "install": "go mod download", "format": "test -z \"$(gofmt -l .)\"",
        "lint": lint, "build": f"go build -o {os.devnull} ./...", "test": "go test ./..."}, ["go"])


def rust_project(root: Path) -> dict | None:
    return simple(root, "Cargo.toml", "rust", {
        "install": "cargo fetch", "format": "cargo fmt --all -- --check",
        "lint": "cargo clippy --all-targets -- -D warnings", "build": "cargo build",
        "test": "cargo test"}, ["cargo"])


def dart_project(root: Path) -> dict | None:
    pubspec = root / "pubspec.yaml"
    if not pubspec.exists():
        return None
    is_flutter = re.search(r"^\s*flutter\s*:", read(pubspec), re.M) is not None
    tool = "flutter" if is_flutter else "dart"
    cmds = {"install": f"{tool} pub get", "format": "dart format --set-exit-if-changed .",
            "lint": f"{tool} analyze", "test": f"{tool} test"}
    if is_flutter:
        cmds["build"] = "flutter build apk --debug"
    return {"stack": "flutter" if is_flutter else "dart", "package_manager": "pub",
            "frameworks": ["flutter"] if is_flutter else [], "commands": cmds,
            "required_tools": [tool]}


def gradle_project(root: Path) -> dict | None:
    if not any((root / f).exists() for f in ("build.gradle", "build.gradle.kts",
                                             "settings.gradle", "settings.gradle.kts")):
        return None
    gw = "./gradlew" if (root / "gradlew").exists() else "gradle"
    text = read(root / "build.gradle") + read(root / "build.gradle.kts")
    for sub in root.glob("*/build.gradle*"):
        text += read(sub)
    android = "com.android" in text or "android {" in text
    cmds = {"install": f"{gw} --version", "lint": f"{gw} lint" if android else f"{gw} check -x test",
            "build": f"{gw} assembleDebug" if android else f"{gw} build -x test",
            "test": f"{gw} testDebugUnitTest" if android else f"{gw} test"}
    return {"stack": "android-gradle" if android else "gradle", "package_manager": "gradle",
            "frameworks": ["android"] if android else [], "commands": cmds,
            "required_tools": ["java"] + ([] if gw == "./gradlew" else ["gradle"])}


def maven_project(root: Path) -> dict | None:
    return simple(root, "pom.xml", "maven", {
        "install": "mvn -q -DskipTests dependency:resolve", "build": "mvn -q -DskipTests package",
        "test": "mvn -q test"}, ["mvn"])


def dotnet_project(root: Path) -> dict | None:
    if not (any(root.glob("*.sln")) or any(root.glob("*.csproj")) or any(root.glob("*.fsproj"))):
        return None
    return {"stack": "dotnet", "package_manager": "nuget", "frameworks": [],
            "commands": {"install": "dotnet restore", "format": "dotnet format --verify-no-changes",
                         "build": "dotnet build --no-restore", "test": "dotnet test --no-build"},
            "required_tools": ["dotnet"]}


def platformio_project(root: Path) -> dict | None:
    return simple(root, "platformio.ini", "platformio", {
        "build": "pio run", "test": "pio test"}, ["pio"])


def arduino_project(root: Path) -> dict | None:
    sketches = list(root.glob("*.ino"))
    if not sketches or (root / "platformio.ini").exists():
        return None
    return {"stack": "arduino", "package_manager": "arduino-cli", "frameworks": [],
            "commands": {"build": "arduino-cli compile --fqbn <FQBN> .  # e.g. esp32:esp32:esp32"},
            "required_tools": ["arduino-cli"],
            "notes": ["Set the board FQBN; read sketch.yaml or the README for the target board."]}


def make_project(root: Path) -> dict | None:
    mk = read(root / "Makefile")
    if not mk:
        return None
    targets = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", mk, re.M))
    cmds = {k: f"make {t}" for k, t in (("lint", "lint"), ("typecheck", "typecheck"),
                                         ("build", "build"), ("test", "test"),
                                         ("format", "fmt-check")) if t in targets}
    if not cmds:
        return None
    return {"stack": "make", "package_manager": "make", "frameworks": [],
            "commands": cmds, "required_tools": ["make"]}


DETECTORS = [node_project, python_project, go_project, rust_project, dart_project,
             gradle_project, maven_project, dotnet_project, platformio_project,
             arduino_project, make_project]


def find_roots(repo: Path, max_depth: int) -> list[Path]:
    roots = []
    for dirpath, dirnames, _ in os.walk(repo):
        here = Path(dirpath)
        depth = len(here.relative_to(repo).parts)
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        if depth >= max_depth:
            dirnames[:] = []
        roots.append(here)
    return roots


def ci_commands(repo: Path) -> list[str]:
    """Commands CI actually runs: the ground truth when it disagrees with guesses."""
    found = []
    for wf in sorted((repo / ".github" / "workflows").glob("*.y*ml")):
        for m in re.finditer(r"^\s*(?:-\s*)?run:\s*(?:\|\s*\n)?(.+)$", read(wf), re.M):
            line = m.group(1).strip()
            if line and line not in ("|", ">"):
                found.append(f"{wf.name}: {line}")
    for name in (".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", "bitbucket-pipelines.yml"):
        if (repo / name).exists():
            found.append(f"{name}: present (read it for the canonical commands)")
    return found


def detect(repo: Path, max_depth: int = 3) -> dict:
    projects = []
    for root in find_roots(repo, max_depth):
        for det in DETECTORS:
            info = det(root)
            if info:
                rel = str(root.relative_to(repo))
                if info["stack"] == "make" and any(p["root"] == rel for p in projects):
                    continue
                info["root"] = rel
                info["commands"] = {k: info["commands"][k] for k in CHECK_ORDER
                                    if info["commands"].get(k)}
                info["missing_tools"] = [t for t in info["required_tools"] if not has(t)]
                projects.append(info)
    instructions = [p for p in ("CLAUDE.md", "AGENTS.md", ".cursorrules", "CONTRIBUTING.md",
                                ".github/copilot-instructions.md", "README.md")
                    if (repo / p).exists()]
    return {"repo": str(repo), "projects": projects, "ci_commands": ci_commands(repo),
            "instruction_files": instructions,
            "has_editorconfig": (repo / ".editorconfig").exists(),
            "has_precommit": (repo / ".pre-commit-config.yaml").exists()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--max-depth", type=int, default=3)
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    result = detect(repo, args.max_depth)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(f"Repository: {repo}")
    if result["instruction_files"]:
        print("Read first: " + ", ".join(result["instruction_files"]))
    if not result["projects"]:
        print("No buildable project detected (docs-only or unknown stack).")
    for p in result["projects"]:
        fw = f" [{', '.join(p['frameworks'])}]" if p["frameworks"] else ""
        print(f"\n== {p['root']}: {p['stack']} via {p['package_manager']}{fw}")
        for k, v in p["commands"].items():
            print(f"  {k:<10} {v}")
        for n in p.get("notes", []):
            print(f"  note       {n}")
        if p["missing_tools"]:
            print(f"  MISSING    {', '.join(p['missing_tools'])} (not on PATH)")
    if result["ci_commands"]:
        print("\nCI runs (canonical, prefer these when they differ):")
        for c in result["ci_commands"][:40]:
            print(f"  {c}")
    if result["has_precommit"]:
        print("\npre-commit configured: run `pre-commit run --files <changed files>`")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
