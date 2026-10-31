#!/usr/bin/env python3
"""PreToolUse(Bash) hook: before any `git commit`, block the commit when
secrets are about to be committed or when the project's own checks fail.

- Secrets (scan_secrets.py over changes since HEAD + untracked): always blocking.
- Checks (verify.py --changed): blocking on FAIL only. UNVERIFIED/skips are
  passed to Claude as context so they get reported, not hidden.
- Escape hatches, for failures proven to pre-exist on the base branch:
  put PRECISION_SKIP_VERIFY=1 in the command, or disable the plugin option
  `verify_on_commit`. Secrets can only be waved through per line with
  `secret-scan: allow` after review.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = ROOT / "skills" / "secret-scan" / "scripts" / "scan_secrets.py"
VERIFY = ROOT / "skills" / "verification-gate" / "scripts" / "verify.py"
COMMIT_RE = re.compile(r"(?:^|[;&|(]\s*|\s)git((?:\s+-[Cc]\s+\S+|\s+--[\w-]+(?:=\S+)?)*)\s+commit\b")


def tail(text: str, n: int = 40) -> str:
    return "\n".join(text.rstrip().splitlines()[-n:])


def repo_dir(cmd: str, cwd: Path, git_opts: str) -> Path:
    m = re.search(r"-C\s+(\S+)", git_opts or "")
    if m:
        target = Path(shlex.split(m.group(1))[0]).expanduser()
        return target if target.is_absolute() else cwd / target
    m = re.match(r"\s*cd\s+(\S+)\s*&&", cmd)
    if m:
        target = Path(shlex.split(m.group(1))[0]).expanduser()
        return target if target.is_absolute() else cwd / target
    return cwd


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("tool_name") != "Bash":
        return 0
    cmd = (payload.get("tool_input") or {}).get("command", "")
    # Ignore "git commit" that only appears inside quoted text (echo, messages, here-docs).
    unquoted = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", cmd.split("<<", 1)[0])
    m = COMMIT_RE.search(unquoted)
    if not m:
        return 0
    repo = repo_dir(cmd, Path(payload.get("cwd") or os.getcwd()), m.group(1))
    if not (repo / ".git").exists() and subprocess.run(
            ["git", "rev-parse", "--git-dir"], cwd=repo, capture_output=True).returncode != 0:
        return 0

    scan = subprocess.run([sys.executable, str(SCAN), str(repo)], capture_output=True, text=True)
    if scan.returncode == 1:
        print("precision-kit blocked this commit: possible secrets in the changes.\n"
              f"{tail(scan.stdout)}\n"
              "Move them to env vars/secret storage (see secret-scan skill), then commit again.",
              file=sys.stderr)
        return 2

    option = os.environ.get("CLAUDE_PLUGIN_OPTION_VERIFY_ON_COMMIT", "true").strip().lower()
    if option in ("false", "0", "no", "off") or "PRECISION_SKIP_VERIFY=1" in cmd:
        return 0
    ver = subprocess.run([sys.executable, str(VERIFY), str(repo), "--changed", "--timeout", "600"],
                         capture_output=True, text=True)
    if ver.returncode == 1:
        print("precision-kit blocked this commit: checks failed for the changed project(s).\n"
              f"{tail(ver.stdout, 60)}\n"
              "Fix the failures (root-cause-debug). If they are proven pre-existing on the base "
              "branch and unrelated, commit with PRECISION_SKIP_VERIFY=1 and say so in the report.",
              file=sys.stderr)
        return 2
    verdict = next((l for l in reversed(ver.stdout.splitlines()) if l.startswith("VERDICT")), "")
    skipped = [l for l in ver.stdout.splitlines() if l.startswith("SKIP ")]
    if verdict and (ver.returncode == 2 or skipped):
        note = verdict + ("\n" + "\n".join(skipped[:15]) if skipped else "")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": "precision-kit pre-commit verification: " + note +
                                 "\nReport skipped/unverified checks honestly."}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a broken guard must not block work silently
        print(f"[precision-kit] pre-commit guard error (commit not blocked): {exc}",
              file=sys.stderr)
        sys.exit(0)
