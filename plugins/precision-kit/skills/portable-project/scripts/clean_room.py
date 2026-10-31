#!/usr/bin/env python3
"""Prove the project works on a machine that is not yours: fresh clone of what
is committed, empty package caches, no global packages, install from the
lockfile, then build and test.

Usage:
  python3 clean_room.py [REPO] [--include-uncommitted] [--compare] [--only build,test]
                        [--reuse-caches] [--keep] [--timeout SEC]

  --include-uncommitted  also copy uncommitted changes and new (non-ignored) files,
                         i.e. what the next commit will contain
  --compare              run the same checks in this working copy too and list
                         checks that pass here but fail in the clean room
  --reuse-caches         keep download caches (faster; still hides global installs)
  --keep                 keep the clean-room directory for inspection

What "clean" means here: only committed files; Python in a fresh venv without
user/global site-packages; PATH stripped of global npm/pnpm/yarn binaries
(only the runtimes stay); isolated npm/yarn/pnpm/pip caches. Exit 0 when
everything that could run passed, 1 on failures, 2 when nothing could run.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERIFY_CANDIDATES = [HERE / "verify.py", HERE.parent.parent / "verification-gate" / "scripts" / "verify.py"]
DETECT_CANDIDATES = [HERE / "detect_stack.py", HERE.parent.parent / "codebase-recon" / "scripts" / "detect_stack.py"]
RUNTIMES = ["node", "npm", "npx", "corepack", "bun", "deno", "go", "gofmt", "cargo", "rustc", "rustup",
            "java", "javac", "dotnet", "flutter", "dart", "pio", "arduino-cli", "make", "git", "gradle", "mvn"]


def sh(cmd: list[str], cwd: Path, env: dict | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def clean_env(work: Path, reuse_caches: bool) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("VIRTUAL_ENV", "CONDA", "PYTHONPATH", "NODE_PATH"))}
    shim = work / "bin"
    shim.mkdir()
    keep_dirs = []
    for tool in RUNTIMES + ["python3", "python"]:
        path = shutil.which(tool)
        if path:
            target = shim / tool
            if not target.exists():
                target.symlink_to(path)
    # Drop directories that hold globally installed CLIs (npm -g, pip --user, pipx, cargo install ...),
    # but keep standard system dirs so compilers and coreutils still work.
    global_dirs = set()
    for tool in ("npm", "pnpm", "yarn"):
        out = shutil.which(tool) and sh([tool, "prefix", "-g"] if tool == "npm" else [tool, "bin", "-g"], Path.cwd())
        if out and out.returncode == 0 and out.stdout.strip():
            p = Path(out.stdout.strip())
            global_dirs |= {str(p), str(p / "bin")}
    global_dirs |= {str(Path.home() / ".local" / "bin"), str(Path.home() / ".npm-global" / "bin"),
                    str(Path.home() / ".yarn" / "bin"), str(Path.home() / ".bun" / "bin")}
    node = shutil.which("node")
    if node:
        global_dirs.add(str(Path(node).resolve().parent))
        global_dirs.add(str(Path(node).parent))
    for d in env.get("PATH", "").split(os.pathsep):
        if d and d not in global_dirs:
            keep_dirs.append(d)
    env["PATH"] = os.pathsep.join([str(shim)] + keep_dirs)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["npm_config_update_notifier"] = "false"
    env["npm_config_fund"] = "false"
    if not reuse_caches:
        cache = work / "cache"
        env.update({"npm_config_cache": str(cache / "npm"), "YARN_CACHE_FOLDER": str(cache / "yarn"),
                    "npm_config_store_dir": str(cache / "pnpm"), "PIP_CACHE_DIR": str(cache / "pip"),
                    "UV_CACHE_DIR": str(cache / "uv"), "POETRY_CACHE_DIR": str(cache / "poetry"),
                    "PUB_CACHE": str(cache / "pub"), "NUGET_PACKAGES": str(cache / "nuget")})
    return env


def prepare_python(src: Path, env: dict, roots: list[str]) -> list[str]:
    notes = []
    py = shutil.which("python3") or shutil.which("python") or sys.executable
    for root in roots:
        d = src / root
        if (d / ".venv").exists():
            continue
        r = sh([py, "-m", "venv", ".venv"], d, env)
        notes.append(f"{root}: fresh venv " + ("created" if r.returncode == 0 else f"FAILED: {r.stderr.strip()[:200]}"))
    if roots:
        first = src / roots[0] / ".venv"
        bindir = first / ("Scripts" if os.name == "nt" else "bin")
        env["PATH"] = os.pathsep.join([str(bindir), env["PATH"]])
        env["VIRTUAL_ENV"] = str(first)
    return notes


def parse_table(out: str) -> dict[str, tuple[str, str]]:
    rows = {}
    for line in out.splitlines():
        m = re.match(r"^(PASS|FAIL|SKIP|PLAN)\s+(\S+)\s+(.*)$", line)
        if m:
            rows[m.group(2)] = (m.group(1), m.group(3))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--include-uncommitted", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--only", default="install,lint,typecheck,build,test")
    ap.add_argument("--reuse-caches", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--timeout", type=int, default=1200)
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    verify = next((p for p in VERIFY_CANDIDATES if p.exists()), None)
    if not verify:
        sys.exit("verify.py not found: install the verification-gate skill alongside this one.")
    if sh(["git", "rev-parse", "--git-dir"], repo).returncode != 0:
        sys.exit("Not a git repository: there is no 'what others receive' to reproduce.")

    work = Path(tempfile.mkdtemp(prefix="clean-room-"))
    src = work / "src"
    code = 2
    try:
        r = sh(["git", "clone", "--quiet", "--no-local", "--no-hardlinks", str(repo), str(src)], work)
        if r.returncode != 0:
            print(f"clone failed: {r.stderr}")
            return 2
        notes = [f"clean copy of commit {sh(['git', 'rev-parse', '--short', 'HEAD'], src).stdout.strip()}"]
        if args.include_uncommitted:
            diff = subprocess.run(["git", "diff", "HEAD", "--binary"], cwd=repo, capture_output=True)
            if diff.stdout:
                ap_ = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=src, input=diff.stdout,
                                     capture_output=True)
                notes.append("uncommitted changes " + ("applied" if ap_.returncode == 0 else
                                                       f"could NOT be applied: {ap_.stderr.decode()[:200]}"))
            untracked = sh(["git", "ls-files", "--others", "--exclude-standard"], repo).stdout.split("\n")
            for f in filter(None, untracked):
                (src / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repo / f, src / f)
            notes.append(f"{len([u for u in untracked if u])} new file(s) copied")
        env = clean_env(work, args.reuse_caches)
        import importlib.util
        spec = importlib.util.spec_from_file_location("detect_stack", next(p for p in DETECT_CANDIDATES if p.exists()))
        det = importlib.util.module_from_spec(spec)
        sys.modules["detect_stack"] = det
        spec.loader.exec_module(det)
        projects = det.detect(src)["projects"]
        notes += prepare_python(src, env, [p["root"] for p in projects if p["stack"] == "python"])
        print("Clean room: " + str(src))
        for n in notes:
            print(f"  - {n}")
        print("  - global CLI directories removed from PATH; user site-packages disabled"
              + ("" if args.reuse_caches else "; empty package caches"))
        print(flush=True)

        checks = args.only
        run = subprocess.run([sys.executable, str(verify), str(src), "--only", checks, "--timeout", str(args.timeout)],
                             cwd=src, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = run.stdout + run.stderr
        print(out.split("=" * 72, 1)[1] if "=" * 72 in out else out)
        code = run.returncode

        if args.compare:
            local = subprocess.run([sys.executable, str(verify), str(repo), "--only",
                                    ",".join(c for c in checks.split(",") if c != "install"), "--timeout",
                                    str(args.timeout)], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
            here, there = parse_table(local.stdout), parse_table(run.stdout)
            diffs = [(k, here[k][0], there.get(k, ("?", ""))[0]) for k in sorted(here)
                     if here[k][0] != there.get(k, ("?", ""))[0]]
            print("## This machine vs clean room")
            if not diffs:
                print("  identical results: no 'works on my machine' differences found")
            for k, a, b in diffs:
                verdict = "PORTABILITY BUG" if a == "PASS" and b == "FAIL" else "differs"
                print(f"  {k:<32} here={a:<5} clean-room={b:<5}  {verdict}")
            if any(a == "PASS" and b == "FAIL" for _, a, b in diffs):
                code = 1
        return code
    finally:
        if args.keep or code == 1 and sys.stdout.isatty():
            print(f"\n(clean room kept at {work})")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
