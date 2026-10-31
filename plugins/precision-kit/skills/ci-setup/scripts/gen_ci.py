#!/usr/bin/env python3
"""Generate a GitHub Actions CI workflow from the repository's own commands.

Usage:
  python3 gen_ci.py [REPO] [--write] [--force] [--output PATH]

One job per detected project (monorepos supported), each running the
project's install -> lint -> typecheck -> build -> test commands with the
right toolchain setup and dependency cache. Prints the YAML; --write saves
it to .github/workflows/ci.yml (refuses to overwrite without --force).
Action versions live in ACTIONS below: confirm they are the latest majors
before committing (see the ci-setup skill).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DETECT_CANDIDATES = [HERE / "detect_stack.py",
                     HERE.parent.parent / "codebase-recon" / "scripts" / "detect_stack.py"]

ACTIONS = {
    "checkout": "actions/checkout@v4",
    "node": "actions/setup-node@v4",
    "python": "actions/setup-python@v5",
    "uv": "astral-sh/setup-uv@v6",
    "go": "actions/setup-go@v5",
    "java": "actions/setup-java@v4",
    "dotnet": "actions/setup-dotnet@v4",
    "flutter": "subosito/flutter-action@v2",
    "rust": "dtolnay/rust-toolchain@stable",
    "rust-cache": "Swatinem/rust-cache@v2",
    "pnpm": "pnpm/action-setup@v4",
    "bun": "oven-sh/setup-bun@v2",
    "cache": "actions/cache@v4",
}


def load_detect():
    path = next((p for p in DETECT_CANDIDATES if p.exists()), None)
    if path is None:
        sys.exit("detect_stack.py not found: install the codebase-recon skill alongside this one.")
    spec = importlib.util.spec_from_file_location("detect_stack", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def q(s: str) -> str:
    return json.dumps(s)


def setup_steps(p: dict, repo: Path) -> list[str]:
    root, wd = p["root"], repo / p["root"]
    rel = lambda f: f if root == "." else f"{root}/{f}"
    stack, pm = p["stack"], p["package_manager"]
    s: list[str] = []
    if stack == "node":
        if pm == "pnpm":
            s.append(f"      - uses: {ACTIONS['pnpm']}")
        if pm == "bun":
            s.append(f"      - uses: {ACTIONS['bun']}")
        else:
            s.append(f"      - uses: {ACTIONS['node']}\n        with:")
            ver_file = next((f for f in (".nvmrc", ".node-version") if (wd / f).exists()), None)
            s.append(f"          node-version-file: {rel(ver_file)}" if ver_file
                     else "          node-version: lts/*")
            lock = {"npm": "package-lock.json", "pnpm": "pnpm-lock.yaml", "yarn": "yarn.lock"}[pm]
            if (wd / lock).exists():
                s.append(f"          cache: {pm}\n          cache-dependency-path: {rel(lock)}")
    elif stack == "python":
        if pm == "uv":
            s.append(f"      - uses: {ACTIONS['uv']}")
        s.append(f"      - uses: {ACTIONS['python']}\n        with:")
        s.append(f"          python-version-file: {rel('.python-version')}"
                 if (wd / ".python-version").exists() else "          python-version: \"3.x\"")
        if pm == "pip":
            s.append("          cache: pip")
        if pm == "poetry":
            s.append("      - run: pipx install poetry")
        if pm == "pdm":
            s.append("      - run: pipx install pdm")
        if pm == "pipenv":
            s.append("      - run: pipx install pipenv")
    elif stack == "go":
        s.append(f"      - uses: {ACTIONS['go']}\n        with:\n          go-version-file: {rel('go.mod')}")
    elif stack == "rust":
        s.append(f"      - uses: {ACTIONS['rust']}\n        with:\n          components: clippy, rustfmt")
        s.append(f"      - uses: {ACTIONS['rust-cache']}\n        with:\n          workspaces: {root}")
    elif stack in ("flutter", "dart"):
        s.append(f"      - uses: {ACTIONS['flutter']}\n        with:\n          channel: stable\n          cache: true")
    elif stack in ("android-gradle", "gradle", "maven"):
        s.append(f"      - uses: {ACTIONS['java']}\n        with:\n          distribution: temurin\n"
                 f"          java-version: \"17\"\n          cache: {'maven' if stack == 'maven' else 'gradle'}")
    elif stack == "dotnet":
        gj = wd / "global.json"
        s.append(f"      - uses: {ACTIONS['dotnet']}\n        with:\n" +
                 (f"          global-json-file: {rel('global.json')}" if gj.exists()
                  else "          dotnet-version: \"8.0.x\""))
    elif stack == "platformio":
        s.append(f"      - uses: {ACTIONS['python']}\n        with:\n          python-version: \"3.x\"")
        s.append("      - run: pip install platformio")
        s.append(f"      - uses: {ACTIONS['cache']}\n        with:\n          path: ~/.platformio\n"
                 f"          key: pio-${{{{ hashFiles('{rel('platformio.ini')}') }}}}")
    return s


def for_ci(cmd: str) -> str:
    """Commands were detected on this machine; make them valid on a fresh Linux runner."""
    cmd = cmd.replace(f"-o {os.devnull} ", "-o /dev/null ")
    return re.sub(r"^\S*(?:\.venv|venv)[/\\]\S*python(?:\.exe)? -m ", "python -m ", cmd)


def job(p: dict, repo: Path, oses: list[str] | None = None) -> str | None:
    cmds = {k: for_ci(v) for k, v in p["commands"].items() if "<" not in v}
    if not cmds:
        return None
    jid = re.sub(r"[^A-Za-z0-9_-]", "-", (p["root"] if p["root"] != "." else "root")) + f"-{p['stack']}"
    lines = [f"  {jid}:", f"    name: {q(p['root'] + ' (' + p['stack'] + ')')}",
             "    runs-on: ${{ matrix.os }}" if oses else "    runs-on: ubuntu-latest", "    timeout-minutes: 30"]
    if oses:
        lines += ["    strategy:", "      fail-fast: false", "      matrix:", f"        os: [{', '.join(oses)}]"]
    if p["root"] != "." or oses:
        lines += ["    defaults:", "      run:"]
        if oses:
            lines.append("        shell: bash  # same commands on Windows (Git Bash), macOS and Linux")
        if p["root"] != ".":
            lines.append(f"        working-directory: {p['root']}")
    lines += ["    steps:", f"      - uses: {ACTIONS['checkout']}"]
    lines += setup_steps(p, repo)
    if p["stack"] == "android-gradle" and (repo / p["root"] / "gradlew").exists():
        lines.append("      - run: chmod +x gradlew")
    for k in ("install", "format", "lint", "typecheck", "build", "test"):
        if k in cmds and not (k == "install" and cmds[k].endswith("--version")):
            lines.append(f"      - name: {k}\n        run: {q(cmds[k])}" if any(c in cmds[k] for c in ":#\"'{}")
                         else f"      - name: {k}\n        run: {cmds[k]}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--output", default=".github/workflows/ci.yml")
    ap.add_argument("--os", help="comma list of runners for a cross-OS matrix, e.g. "
                                 "ubuntu-latest,windows-latest,macos-latest")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    det = load_detect().detect(repo)
    oses = [o.strip() for o in args.os.split(",") if o.strip()] if args.os else None
    jobs = [j for j in (job(p, repo, oses) for p in det["projects"]) if j]
    skipped = [p["root"] + f" ({p['stack']})" for p in det["projects"]
               if not job(p, repo)]
    if not jobs:
        print("No project with runnable commands detected; nothing to generate.", file=sys.stderr)
        return 2
    yaml = "\n".join([
        "name: CI", "",
        "on:", "  push:", "    branches: [main, master]", "  pull_request:", "  workflow_dispatch:", "",
        "permissions:", "  contents: read", "",
        "concurrency:", "  group: ci-${{ github.ref }}", "  cancel-in-progress: true", "",
        "jobs:", "\n\n".join(jobs), ""])
    if skipped:
        yaml += "".join(f"# not generated (needs manual setup): {s}\n" for s in skipped)
    if not args.write:
        print(yaml, end="")
        return 0
    out = repo / args.output
    if out.exists() and not args.force:
        print(f"{args.output} exists; review the printed YAML and merge by hand, or pass --force.",
              file=sys.stderr)
        print(yaml, end="")
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml, encoding="utf-8")
    print(f"wrote {args.output} ({len(jobs)} job(s))")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
