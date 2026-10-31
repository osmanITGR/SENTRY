#!/usr/bin/env python3
"""Find candidates for safe removal: unreferenced symbols, orphan files,
deprecated markers and commented-out code.

Usage:
  python3 find_dead_code.py [REPO_ROOT] [--path SUBDIR] [--limit N] [--no-tools]

Works on any language with no dependencies (git + regex), then runs a real
analyzer when one is installed (knip, vulture, staticcheck/deadcode).
Everything printed is a CANDIDATE. Confirm each one with a reference search
and a passing build/test before deleting: dynamic dispatch, reflection,
string-based lookups, public APIs and framework callbacks are invisible to
static text matching.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

SOURCE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte",
              ".go", ".rs", ".dart", ".java", ".kt", ".kts", ".cs", ".c", ".h", ".cc",
              ".cpp", ".hpp", ".ino", ".swift", ".rb", ".php"}
TEXT_EXT = SOURCE_EXT | {".json", ".yaml", ".yml", ".toml", ".xml", ".html", ".md",
                         ".gradle", ".cfg", ".ini", ".txt", ".css", ".scss", ".sh",
                         ".iss", ".plist", ".arb", ".graphql", ".sql"}

# Names called by frameworks, runtimes or conventions rather than by repo code.
IMPLICIT = {
    "main", "setup", "loop", "init", "run", "start", "stop", "handler", "handle",
    "render", "build", "dispose", "initState", "didChangeDependencies", "didUpdateWidget",
    "createState", "constructor", "toString", "hashCode", "equals", "toJson", "fromJson",
    "onCreate", "onStart", "onResume", "onPause", "onStop", "onDestroy", "onCreateView",
    "componentDidMount", "componentWillUnmount", "ngOnInit", "ngOnDestroy", "mounted",
    "created", "setUp", "tearDown", "setUpClass", "tearDownClass", "default", "Default",
    "fmt", "drop", "new", "from", "into", "clone", "serialize", "deserialize", "Main",
    "ServeHTTP", "String", "Error", "Len", "Less", "Swap", "MarshalJSON", "UnmarshalJSON",
    "getStaticProps", "getServerSideProps", "generateMetadata", "middleware", "config",
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "app", "App",
    "ISR", "SIGNAL", "serialEvent",
}
ENTRY_STEMS = {"index", "main", "app", "__init__", "__main__", "setup", "conftest",
               "manage", "wsgi", "asgi", "server", "cli", "mod", "lib", "build", "page",
               "layout", "route", "middleware", "vite.config", "next.config",
               "webpack.config", "jest.config", "vitest.config", "tailwind.config",
               "postcss.config", "eslint.config", "babel.config", "metro.config"}

DEF_PATTERNS = {
    ".py": [r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", r"^\s*class\s+([A-Za-z_]\w*)"],
    ".js": [r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)",
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>",
            r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)",
            r"^\s*export\s+(?:interface|type|enum|const)\s+([A-Za-z_$][\w$]*)"],
    ".go": [r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*[\[(]", r"^type\s+([A-Za-z_]\w*)\s"],
    ".rs": [r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:const\s+)?fn\s+([A-Za-z_]\w*)",
            r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)"],
    ".dart": [r"^\s*(?:abstract\s+)?class\s+([A-Za-z_]\w*)",
              r"^\s*(?:static\s+)?(?:Future(?:<[^>]*>)?|Stream(?:<[^>]*>)?|void|int|double|bool|String|Widget|[A-Z]\w*(?:<[^>]*>)?\??)\s+([a-z_]\w*)\s*\("],
    ".java": [r"^\s*(?:public|private|protected|static|final|abstract|synchronized|\s)*[\w<>\[\],\s]+\s+([a-z_]\w*)\s*\([^;]*$",
              r"^\s*(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?(?:class|interface|enum)\s+([A-Za-z_]\w*)"],
    ".kt": [r"^\s*(?:(?:private|internal|public|protected|override|suspend|inline)\s+)*fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?([A-Za-z_]\w*)\s*\(",
            r"^\s*(?:(?:private|internal|public|data|sealed|abstract|open)\s+)*(?:class|object|interface)\s+([A-Za-z_]\w*)"],
    ".cs": [r"^\s*(?:public|private|protected|internal|static|async|virtual|override|\s)+[\w<>\[\],?\s]+\s+([A-Z]\w*)\s*\([^;]*$",
            r"^\s*(?:public|private|protected|internal|static|sealed|abstract|partial|\s)*(?:class|interface|struct|enum|record)\s+([A-Za-z_]\w*)"],
    ".c": [r"^(?!\s)(?:static\s+|inline\s+|extern\s+)*[A-Za-z_][\w\s\*]*?\b([A-Za-z_]\w*)\s*\([^;]*\)\s*\{?\s*$"],
}
for alias, base in ((".jsx", ".js"), (".ts", ".js"), (".tsx", ".js"), (".mjs", ".js"),
                    (".cjs", ".js"), (".vue", ".js"), (".svelte", ".js"), (".kts", ".kt"),
                    (".h", ".c"), (".cc", ".c"), (".cpp", ".c"), (".hpp", ".c"), (".ino", ".c")):
    DEF_PATTERNS[alias] = DEF_PATTERNS[base]
COMPILED = {k: [re.compile(p) for p in v] for k, v in DEF_PATTERNS.items()}
C_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "else", "case", "do"}

TEST_RE = re.compile(r"(^|/)(tests?|__tests__|spec|test_\w+|\w+_test|\w+\.(test|spec))(/|\.|$)")
DEPRECATED_RE = re.compile(r"@deprecated|\bDEPRECATED\b|@Deprecated|\[Obsolete|#\[deprecated|"
                           r"\blegacy\b|no longer used|TODO:?\s*remove|FIXME:?\s*remove|"
                           r"remove (?:this|me|after|once)", re.I)
COMMENT_RE = re.compile(r"^\s*(#|//|--)\s?(.*)$")
CODEISH_RE = re.compile(r"[;{}]\s*$|^\s*(if|for|while|return|def|function|const|let|var|import|"
                        r"from|class|print|console\.|self\.|this\.)\b|\w+\(.*\)\s*;?$|\w+\s*=\s*\S")


def git_files(repo: Path, sub: str | None) -> list[Path]:
    args = ["git", "ls-files", "-co", "--exclude-standard"] + ([sub] if sub else [])
    out = subprocess.run(args, cwd=repo, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("Not a git repository (needed to respect .gitignore).")
    return [repo / l for l in out.stdout.splitlines() if l]


def read(p: Path) -> str:
    try:
        if p.stat().st_size > 1_000_000:
            return ""
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def is_generated(text: str) -> bool:
    head = text[:600].lower()
    return "generated" in head and ("do not edit" in head or "@generated" in head
                                    or "auto-generated" in head or "autogenerated" in head)


def implicit(name: str, ext: str) -> bool:
    if name in IMPLICIT or name.startswith("__") or len(name) <= 2:
        return True
    if name.startswith(("test", "Test", "bench", "Benchmark", "Example", "Fuzz", "_test")):
        return True
    if ext in (".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte") and name.startswith("use") \
            and name[3:4].isupper():
        return False  # React hooks are regular call sites: keep checking them
    if ext == ".py" and name.startswith(("visit_", "do_", "on_", "handle_")):
        return True  # dispatch-by-name conventions
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--path", help="only report definitions under this subdirectory")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--exclude", action="append", default=[".claude/"],
                    help="path prefix to skip (repeatable; .claude/ is skipped by default)")
    ap.add_argument("--no-tools", action="store_true", help="skip external analyzers")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    all_files = git_files(repo, None)
    texts: dict[Path, str] = {}
    tokens: Counter[str] = Counter()
    for f in all_files:
        if f.suffix in TEXT_EXT or f.name in ("Makefile", "Dockerfile"):
            t = read(f)
            texts[f] = t
            tokens.update(re.findall(r"[A-Za-z_$][\w$]*", t))

    corpus = "\n".join(texts.values())
    scope = [f for f in texts if f.suffix in SOURCE_EXT and
             not str(f.relative_to(repo)).startswith(tuple(args.exclude)) and
             (not args.path or str(f.relative_to(repo)).startswith(args.path.rstrip("/")))]

    unused, deprecated, commented, orphans = [], [], [], []
    for f in scope:
        rel = str(f.relative_to(repo))
        text = texts[f]
        if is_generated(text):
            continue
        is_test = bool(TEST_RE.search(rel))
        lines = text.splitlines()
        pats = COMPILED.get(f.suffix, [])
        run_start, run_len = None, 0
        for i, line in enumerate(lines, 1):
            if not is_test:
                for pat in pats:
                    m = pat.match(line)
                    if not m:
                        continue
                    name = m.group(1)
                    if name in C_KEYWORDS or implicit(name, f.suffix):
                        continue
                    if tokens[name] <= 1:
                        unused.append((rel, i, name, line.strip()[:90]))
                    break
            if DEPRECATED_RE.search(line):
                deprecated.append((rel, i, line.strip()[:100]))
            cm = COMMENT_RE.match(line)
            if cm and CODEISH_RE.search(cm.group(2)):
                if run_start is None:
                    run_start = i
                run_len += 1
            else:
                if run_len >= 3:
                    commented.append((rel, run_start, run_len))
                run_start, run_len = None, 0
        if run_len >= 3:
            commented.append((rel, run_start, run_len))

        stem = f.stem.split(".")[0]
        if not is_test and f.stem not in ENTRY_STEMS and stem not in ENTRY_STEMS \
                and f.suffix not in (".h", ".hpp", ".ino"):
            if corpus.count(stem) - text.count(stem) <= 0:
                orphans.append(rel)

    def section(title: str, rows: list, fmt) -> None:
        print(f"\n## {title} ({len(rows)})")
        for r in rows[:args.limit]:
            print("  " + fmt(r))
        if len(rows) > args.limit:
            print(f"  ... {len(rows) - args.limit} more (use --limit or --path)")

    print(f"Scanned {len(scope)} source files ({len(texts)} text files indexed) in {repo}")
    section("Symbols defined but never referenced elsewhere", unused,
            lambda r: f"{r[0]}:{r[1]}  {r[2]}    | {r[3]}")
    section("Files whose name is never mentioned by another file (possible orphans)",
            orphans, lambda r: r)
    section("Deprecated / legacy / remove-me markers", deprecated,
            lambda r: f"{r[0]}:{r[1]}  {r[2]}")
    section("Commented-out code blocks (>=3 lines)", commented,
            lambda r: f"{r[0]}:{r[1]}  ({r[2]} lines)")

    if not args.no_tools:
        print("\n## Real analyzers")
        ran = False
        for root in sorted({p.parent for p in all_files if p.name == "package.json"}):
            for tool in ("knip", "ts-prune"):
                if (root / "node_modules" / ".bin" / tool).exists():
                    ran = True
                    print(f"$ ({root.relative_to(repo)}) npx --no-install {tool}")
                    out = subprocess.run(["npx", "--no-install", tool], cwd=root,
                                         capture_output=True, text=True, timeout=600)
                    print("\n".join((out.stdout + out.stderr).splitlines()[:80]))
                    break
        if any(f.suffix == ".py" for f in scope) and shutil.which("vulture"):
            ran = True
            target = args.path or "."
            print(f"$ vulture {target} --min-confidence 80")
            out = subprocess.run(["vulture", target, "--min-confidence", "80",
                                  "--exclude", ".venv,venv,node_modules"],
                                 cwd=repo, capture_output=True, text=True)
            print("\n".join(out.stdout.splitlines()[:80]))
        if (repo / "go.mod").exists():
            for tool, cmd in (("deadcode", ["deadcode", "./..."]),
                              ("staticcheck", ["staticcheck", "-checks", "U1000", "./..."])):
                if shutil.which(tool):
                    ran = True
                    print("$ " + " ".join(cmd))
                    out = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
                    print("\n".join((out.stdout + out.stderr).splitlines()[:80]))
                    break
        if not ran:
            print("  none installed. Precise options: JS/TS `npx knip`, Python `vulture`, "
                  "Go `deadcode ./...`, Rust `cargo build` (dead_code warnings), "
                  "Dart `dart analyze` (unused_element), C# IDE0051/IDE0052.")
    print("\nNext: confirm every candidate with a whole-repo reference search "
          "(including strings, configs, reflection, public API consumers) before deleting.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
