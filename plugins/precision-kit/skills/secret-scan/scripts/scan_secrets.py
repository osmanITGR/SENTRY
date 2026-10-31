#!/usr/bin/env python3
"""Find credentials before they are committed.

Usage:
  python3 scan_secrets.py [REPO] [--mode changed|staged|all] [PATH ...]

Modes:
  changed (default)  lines added since HEAD (staged + unstaged) and untracked files
  staged             lines added in the index only (what `git commit` would record)
  all                every tracked file (audit an existing repository)
Explicit PATHs scan those files completely.

Exit 1 when anything is found, 0 when clean. Values are masked in the output.
Suppress a reviewed false positive with `secret-scan: allow` (or
`pragma: allowlist secret`) on the same line. Standard library only.
"""
# audit: allow-file - this file defines detection patterns; scanning it would flag the rules themselves
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

RULES: list[tuple[str, re.Pattern]] = [(name, re.compile(rx)) for name, rx in (
    ("private key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"),
    ("AWS access key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    ("GitLab token", r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    ("Slack token", r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b"),
    ("Slack webhook", r"https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,}"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("Stripe live key", r"\b(?:sk|rk)_live_[0-9a-zA-Z]{20,}\b"),
    ("Anthropic API key", r"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    ("OpenAI API key", r"\bsk-(?!ant-)(?:proj-)?[A-Za-z0-9_-]{32,}"),
    ("npm token", r"\bnpm_[A-Za-z0-9]{36}\b"),
    ("Twilio key", r"\bSK[0-9a-fA-F]{32}\b"),
    ("SendGrid key", r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b"),
    ("JWT", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ("credentials in URL", r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:([^\s@/'\"]{4,})@[^\s'\"]+"),
    ("hard-coded secret", r"(?i)\b[\w.-]*(?:password|passwd|pwd|secret|api[_-]?key|apikey|"
                          r"access[_-]?token|auth[_-]?token|private[_-]?key|client[_-]?secret)"
                          r"[\w.-]*['\"]?\s*(?:=|:|:=|=>)\s*['\"]([^'\"\s]{8,})['\"]"),
    ("secret in KEY=value config", r"^\s*(?:export\s+|ENV\s+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|"
                                   r"PRIVATE_KEY|ACCESS_KEY|CLIENT_SECRET|AUTH_KEY)[A-Z0-9_]*\s*[=:]\s*([^\s#'\"]{8,})\s*$"),
    ("credentials passed as string literals",
     r"\b(?:begin|connect|login|authenticate|signIn\w*)\(\s*\"[^\"]{1,64}\"\s*,\s*\"([^\"]{8,})\""),
)]
SENSITIVE_FILES = re.compile(
    r"(^|/)(\.env(\.[\w-]+)?|[^/]+\.env|id_(rsa|dsa|ecdsa|ed25519)|.*\.(pem|key|p12|pfx|jks|keystore|"
    r"ppk|mobileprovision)|credentials\.json|service[-_]account.*\.json|\.npmrc|\.pypirc|"
    r"secrets?\.(ya?ml|json|toml))$", re.I)
SAFE_FILES = re.compile(r"(^|/)\.env\.(example|sample|template|dist)$|\.lock$|-lock\.json$|"
                        r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.sum|Cargo\.lock)$")
PLACEHOLDER = re.compile(
    r"(?i)^(x+|\*+|\.+|<.*>|\{.*\}|\$\{.*\}|\$\(.*\)|%\(.*\)s?|\$[A-Z_]+|changeme|change_me|"
    r"password|secret|example|sample|dummy|test(ing)?|fake|placeholder|your[_-].*|my[_-].*|"
    r"redacted|todo|none|null|undefined|process\.env.*|os\.environ.*|env\(.*\))$")
ALLOW = re.compile(r"secret-scan:\s*allow|pragma:\s*allowlist secret", re.I)


def git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout if out.returncode == 0 else ""


def added_lines(diff: str):
    """Yield (path, line_no, text) for every '+' line of a unified diff."""
    path, line_no = None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else None
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) - 1 if m else 0
        elif path and raw.startswith("+"):
            line_no += 1
            yield path, line_no, raw[1:]
        elif path and not raw.startswith("-"):
            line_no += 1


def file_lines(repo: Path, rel: str):
    p = repo / rel
    try:
        if p.stat().st_size > 2_000_000:
            return
        data = p.read_bytes()
    except OSError:
        return
    if b"\0" in data[:8000]:
        return
    for i, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        yield rel, i, line


def mask(value: str) -> str:
    return value[:4] + "*" * max(4, len(value) - 6) + value[-2:] if len(value) > 8 else "****"


def scan_line(text: str):
    if ALLOW.search(text):
        return
    for name, rx in RULES:
        for m in rx.finditer(text):
            value = m.group(m.lastindex or 0)
            if name in ("hard-coded secret", "credentials in URL", "secret in KEY=value config",
                        "credentials passed as string literals"):
                if PLACEHOLDER.match(value) or len(set(value)) < 4:
                    continue
                if name == "hard-coded secret" and re.fullmatch(r"[a-z]+(?:[-_.][a-z]+)*", value):
                    continue  # lowercase words only: an identifier/name, not a credential
            yield name, value


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--mode", choices=["changed", "staged", "all"], default="changed")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    sources, files, names = [], [], []
    if args.paths:
        files = args.paths
    elif args.mode == "all":
        files = git(repo, "ls-files").splitlines()
    else:
        diff_args = ["diff", "--cached"] if args.mode == "staged" else ["diff", "HEAD"]
        diff = git(repo, *diff_args, "--no-color", "-U0", "--diff-filter=ACMR")
        if not diff and args.mode == "changed" and not git(repo, "rev-parse", "--verify", "HEAD"):
            diff = git(repo, "diff", "--cached", "--no-color", "-U0")  # no commits yet
        sources.append(added_lines(diff))
        names += git(repo, *diff_args, "--name-only", "--diff-filter=ACMR").splitlines()
        if args.mode == "changed":
            files = git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
            names += files
        for n in names:
            if SENSITIVE_FILES.search(n) and not SAFE_FILES.search(n):
                print(f"SENSITIVE FILE  {n}  (should almost never be committed; add to .gitignore)")
    sources += [file_lines(repo, f) for f in files]

    findings = 0
    for src in sources:
        for path, line_no, text in src:
            if SAFE_FILES.search(path):
                continue
            for name, value in scan_line(text):
                findings += 1
                print(f"{path}:{line_no}  {name}: {mask(value)}")
    sensitive = [n for n in names if SENSITIVE_FILES.search(n) and not SAFE_FILES.search(n)]
    total = findings + len(sensitive)
    if total:
        print(f"\n{total} potential secret(s). Move values to environment variables / a secret "
              "store, rotate any real credential that was exposed, and keep sensitive files in "
              ".gitignore. Mark a reviewed false positive with `secret-scan: allow`.")
        return 1
    print("secret-scan: clean")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):  # UTF-8 output even on legacy Windows consoles
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
