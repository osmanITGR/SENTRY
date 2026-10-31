#!/usr/bin/env python3
"""Find deprecated API usage in the running code, as reported by the project's
own toolchain (compilers, linters, test runs with deprecation warnings on).

Usage:
  python3 find_deprecations.py [REPO] [--root PATH] [--timeout SEC] [--limit N]

Runs each project's lint/typecheck/build/test commands (from detect_stack.py)
with deprecation reporting switched on (PYTHONWARNINGS, --trace-deprecation,
Gradle --warning-mode all), plus staticcheck SA1019 for Go when installed,
and prints each distinct deprecation message with its file:line. Run it
before and after upgrading: new versions announce their deprecations here.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DETECT_CANDIDATES = [HERE / "detect_stack.py",
                     HERE.parent.parent / "codebase-recon" / "scripts" / "detect_stack.py"]
DEPRECATION_RE = re.compile(r"deprecat|obsolete|will be removed|no longer supported|"
                            r"scheduled for removal|SA1019|deprecated_member_use", re.I)
LOCATION_RE = re.compile(r"([\w./\\-]+\.[A-Za-z]{1,6})[:(](\d+)")


def load_detect():
    path = next((p for p in DETECT_CANDIDATES if p.exists()), None)
    if path is None:
        sys.exit("detect_stack.py not found: install the codebase-recon skill alongside this one.")
    spec = importlib.util.spec_from_file_location("detect_stack", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def env_with_deprecations() -> dict:
    env = dict(os.environ)
    env["PYTHONWARNINGS"] = "default::DeprecationWarning,default::PendingDeprecationWarning,default::FutureWarning"
    env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + " --trace-deprecation").strip()
    env["RUSTFLAGS"] = (env.get("RUSTFLAGS", "") + " -W deprecated").strip()
    return env


def own_location(line: str, cwd: Path):
    """file:line in the project (not runtime internals like node:buffer:193)."""
    for m in LOCATION_RE.finditer(line.replace("file://", "")):
        path = m.group(1)
        if path.startswith(("node:", "internal/")) or "<frozen" in line:
            continue
        candidate = Path(path) if Path(path).is_absolute() else cwd / path
        if candidate.exists():
            try:
                rel = candidate.resolve().relative_to(cwd.resolve())
            except ValueError:
                rel = Path(path)
            return rel.as_posix(), m.group(2)
    return None


def normalise(line: str) -> str:
    """Collapse numbers/addresses so repeated warnings dedupe."""
    return re.sub(r"0x[0-9a-f]+|\(node:\d+\)|\d+ms", "", line).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--root", help="only this project root")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    det = load_detect().detect(repo)
    projects = [p for p in det["projects"] if not args.root or p["root"] == args.root.strip("/")]
    env = env_with_deprecations()
    found: dict[str, tuple[str, str]] = {}
    ran, skipped = [], []

    for p in projects:
        cwd = repo / p["root"]
        cmds = [p["commands"][k] for k in ("lint", "typecheck", "build", "test") if p["commands"].get(k)]
        if p["stack"] in ("android-gradle", "gradle"):
            cmds = [c + " --warning-mode all" if c.startswith(("./gradlew", "gradle")) else c for c in cmds]
        if p["stack"] == "go" and shutil.which("staticcheck"):
            cmds.append("staticcheck -checks SA1019 ./...")
        for cmd in cmds:
            tool = cmd.split()[0]
            path_like = "/" in tool or "\\" in tool
            if "<" in cmd or (tool != "test" and not ((cwd / tool).exists() if path_like else shutil.which(tool))):
                skipped.append(f"{p['root']}: {cmd}")
                continue
            ran.append(f"{p['root']}: {cmd}")
            try:
                # audit: allow - runs the project's own command lines
                out = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                     timeout=args.timeout, env=env)
                text = (out.stdout or "") + (out.stderr or "")
            except subprocess.TimeoutExpired:
                skipped.append(f"{p['root']}: {cmd} (timed out)")
                continue
            lines = text.splitlines()
            for i, line in enumerate(lines):
                bare = line.lstrip("#| \t")
                if not DEPRECATION_RE.search(line) or len(line) > 600 or bare.startswith("at "):
                    continue
                loc = own_location(line, cwd)
                for near in lines[i + 1:i + 12] + lines[max(0, i - 2):i][::-1]:  # stack trace / preceding line
                    loc = loc or own_location(near, cwd)
                prefix = "" if p["root"] == "." else p["root"] + "/"
                where = f"{prefix}{loc[0]}:{loc[1]}" if loc else f"{p['root']} (location not reported)"
                key = normalise(line)
                if "node_modules" in where or "site-packages" in where:
                    where = f"(dependency) {where}"
                found.setdefault(key, (where, line.strip()[:300]))

    print(f"Ran {len(ran)} command(s) with deprecation reporting on.")
    for s in skipped:
        print(f"  SKIP {s}")
    own = [(w, l) for w, l in found.values() if not w.startswith("(dependency)")]
    deps = [(w, l) for w, l in found.values() if w.startswith("(dependency)")]
    print(f"\n## Deprecated usage in this repository's code ({len(own)})")
    for where, line in own[:args.limit]:
        print(f"  {where}\n      {line}")
    if deps:
        print(f"\n## Deprecations raised inside dependencies ({len(deps)}) - usually fixed by upgrading them")
        for where, line in deps[:20]:
            print(f"  {where}\n      {line}")
    if not ran:
        print("\nNothing could run: deprecations NOT checked. Install the toolchain or run the "
              "project's linter with its deprecation rule (e.g. @typescript-eslint/no-deprecated).")
        return 2
    return 1 if own else 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
