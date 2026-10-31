#!/usr/bin/env python3
"""Run every check the repository defines and report an honest verdict.

Usage:
  python3 verify.py [REPO_ROOT] [--only lint,test] [--changed] [--root PATH]
                    [--include-install] [--include-format] [--timeout SEC] [--dry-run]

Uses detect_stack.py to find projects and their own commands, then runs
lint -> typecheck -> build -> test for each. Every check ends as PASS, FAIL
or SKIP (with the reason), never silently omitted. Exit code is 1 if any
check failed, 2 if nothing at all could be verified, else 0.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Bundled copy first (standalone installs), then the sibling codebase-recon skill.
DETECT_CANDIDATES = [HERE / "detect_stack.py",
                     HERE.parent.parent / "codebase-recon" / "scripts" / "detect_stack.py"]


def load_detect():
    path = next((p for p in DETECT_CANDIDATES if p.exists()), None)
    if path is None:
        sys.exit("detect_stack.py not found: install the codebase-recon skill alongside this one.")
    spec = importlib.util.spec_from_file_location("detect_stack", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def changed_files(repo: Path) -> list[str]:
    files: set[str] = set()
    for args in (["git", "diff", "--name-only", "HEAD"],
                 ["git", "ls-files", "--others", "--exclude-standard"]):
        out = subprocess.run(args, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
        files.update(l for l in out.stdout.splitlines() if l)
    base = subprocess.run(["git", "merge-base", "HEAD", "origin/HEAD"], cwd=repo,
                          capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
    if base:
        out = subprocess.run(["git", "diff", "--name-only", base, "HEAD"], cwd=repo,
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        files.update(l for l in out.stdout.splitlines() if l)
    return sorted(files)


def owns(root: str, path: str) -> bool:
    return root == "." or path == root or path.startswith(root.rstrip("/") + "/")


def first_tool(cmd: str) -> str:
    for tok in cmd.split():
        if "=" in tok and not tok.startswith(("-", "./")):
            continue  # env assignment
        return tok
    return ""


def missing_python_module(cmd: str, cwd: Path) -> str | None:
    """`python -m mod` exits 1 when mod is absent: that is a SKIP, not a FAIL."""
    m = re.match(r"\s*(\S*python3?)\s+-m\s+([\w.]+)", cmd)
    if not m:
        return None
    py, mod = m.groups()
    probe = subprocess.run([py, "-c", f"import importlib.util,sys;"
                            f"sys.exit(importlib.util.find_spec({mod!r}) is None)"],
                           cwd=cwd, capture_output=True)
    return None if probe.returncode == 0 else mod


def tool_available(tool: str, cwd: Path) -> bool:
    """Bare names are looked up on PATH; paths (./gradlew, .venv/bin/python) relative to the project."""
    if "/" in tool or "\\" in tool:
        return (cwd / tool).exists() or Path(tool).exists()
    return shutil.which(tool) is not None


def run(cmd: str, cwd: Path, timeout: int) -> tuple[int, str, float]:
    start = time.monotonic()
    try:
        # audit: allow - runs the project's own command lines (&&, pipes), never user-supplied input
        proc = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, out, time.monotonic() - start
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, out + f"\n[timed out after {timeout}s]", time.monotonic() - start


def tail(text: str, n: int = 60) -> str:
    lines = text.rstrip().splitlines()
    return "\n".join(lines[-n:])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--only", help="comma list of checks: format,lint,typecheck,build,test")
    ap.add_argument("--changed", action="store_true",
                    help="only projects that contain changed/untracked files")
    ap.add_argument("--root", help="only this project root (relative path)")
    ap.add_argument("--include-install", action="store_true")
    ap.add_argument("--include-format", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    det = load_detect().detect(repo)
    checks = ["lint", "typecheck", "build", "test"]
    if args.include_format:
        checks.insert(0, "format")
    if args.include_install:
        checks.insert(0, "install")
    if args.only:
        checks = [c.strip() for c in args.only.split(",") if c.strip()]

    projects = det["projects"]
    if args.root:
        projects = [p for p in projects if p["root"] == args.root.strip("/") or
                    (args.root in (".", "") and p["root"] == ".")]
    if args.changed:
        files = changed_files(repo)
        print(f"Changed files ({len(files)}): " + ", ".join(files[:15])
              + (" ..." if len(files) > 15 else ""))
        projects = [p for p in projects if any(owns(p["root"], f) for f in files)]
        # Prefer the most specific root that owns each file (skip "." if a sub-root owns all).
        specific = [p for p in projects if p["root"] != "."]
        if specific and all(any(owns(p["root"], f) for p in specific) for f in files):
            projects = specific

    if not projects:
        print("VERDICT: NOTHING TO VERIFY - no project/check matched. Say so explicitly; "
              "do not claim the change is tested.")
        return 2

    results = []
    for p in projects:
        cwd = repo / p["root"]
        for check in checks:
            cmd = p["commands"].get(check)
            label = f"{p['root']}:{check}"
            if not cmd:
                results.append((label, "SKIP", "no command defined", 0.0, ""))
                continue
            if "<" in cmd and ">" in cmd:
                results.append((label, "SKIP", f"needs a parameter: {cmd}", 0.0, ""))
                continue
            tool = first_tool(cmd)
            if tool and tool not in ("test", "true") and not tool_available(tool, cwd):
                results.append((label, "SKIP", f"`{tool}` not installed", 0.0, ""))
                continue
            mod = missing_python_module(cmd, cwd)
            if mod:
                results.append((label, "SKIP", f"python module `{mod}` not installed", 0.0, ""))
                continue
            if args.dry_run:
                results.append((label, "PLAN", cmd, 0.0, ""))
                continue
            print(f"-> {label}: {cmd}", flush=True)
            code, out, secs = run(cmd, cwd, args.timeout)
            results.append((label, "PASS" if code == 0 else "FAIL", cmd, secs, out))

    print("\n" + "=" * 72)
    for label, status, detail, secs, _ in results:
        t = f" ({secs:.1f}s)" if secs else ""
        print(f"{status:<5} {label:<32} {detail}{t}")
    failed = [r for r in results if r[1] == "FAIL"]
    for label, _, cmd, _, out in failed:
        print(f"\n--- FAIL {label}: {cmd}\n{tail(out)}")
    passed = [r for r in results if r[1] == "PASS"]
    skipped = [r for r in results if r[1] == "SKIP"]
    print("=" * 72)
    if args.dry_run:
        print("VERDICT: DRY RUN")
        return 0
    if failed:
        print(f"VERDICT: FAIL - {len(failed)} failed, {len(passed)} passed, {len(skipped)} skipped")
        return 1
    if not passed:
        print("VERDICT: UNVERIFIED - every check was skipped. Report this; do not claim success.")
        return 2
    print(f"VERDICT: PASS - {len(passed)} passed, {len(skipped)} skipped"
          + (" (mention skipped checks in the report)" if skipped else ""))
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
