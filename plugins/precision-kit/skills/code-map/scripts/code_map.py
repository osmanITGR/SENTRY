#!/usr/bin/env python3
"""Persistent, incrementally updated map of a codebase, so an agent reads only
the lines it needs instead of whole files.

Usage (run from anywhere inside the repo, or pass --repo):
  code_map.py summary [--path DIR] [--max-symbols N]   project overview (read this first)
  code_map.py find QUERY [--kind K] [--limit N]        symbols/files matching QUERY -> path:start-end
  code_map.py show PATH                                outline of one file: symbols + line ranges, deps
  code_map.py refs NAME [--limit N]                    every use of NAME, with the enclosing symbol
  code_map.py deps PATH [--depth N]                    imports and reverse imports (impact radius)
  code_map.py note PATH "purpose"                      record what a file/dir (dir/) is for
  code_map.py stale                                    notes whose file changed shape since written
  code_map.py update | build | stats

Every query first re-indexes only the files that changed (mtime/size, then
content hash), so the map is always current. Index and MAP.md live in
<repo>/.claude/code-map/ (gitignored); notes.json there is meant to be committed.
Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

VERSION = 3
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "vendor", ".dart_tool",
             ".gradle", "__pycache__", "out", "bin", "obj", ".next", ".nuxt", "coverage", ".idea", "Pods"}
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".go", ".rs", ".java",
            ".kt", ".kts", ".cs", ".dart", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".ino", ".php", ".rb",
            ".scala", ".m", ".mm", ".lua", ".sh"}
OTHER_EXT = {".json", ".yml", ".yaml", ".toml", ".md", ".xml", ".gradle", ".properties", ".sql", ".html",
             ".css", ".scss", ".ini", ".cfg", ".proto", ".graphql", ".iss", ".env.example"}
OTHER_NAMES = {"Dockerfile", "Makefile", "CMakeLists.txt", "Procfile", "Gemfile", "Podfile", "go.mod", "go.work"}
SKIP_FILES = re.compile(r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock|"
                        r"Cargo\.lock|go\.sum|pubspec\.lock|composer\.lock|Gemfile\.lock)$|\.min\.(js|css)$|\.map$")
KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "new", "else", "do", "try",
            "sizeof", "typeof", "await", "throw", "case", "with", "elif", "when", "match", "using", "lock",
            "foreach", "super", "this", "constructor", "import", "export", "delete", "void", "in", "of"}


# ------------------------------------------------------------------ parsing
def strip_code(line: str) -> str:
    line = re.sub(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`", "\"\"", line)
    line = re.sub(r"/\*.*?\*/", "", line)
    return re.split(r"//", line, maxsplit=1)[0]


def block_end(lines: list[str], start: int) -> int:
    """Index of the line closing the brace block opened at/after `start`."""
    depth, seen, parens = 0, False, 0
    for j in range(start, len(lines)):
        for ch in strip_code(lines[j]):
            if ch in "([":
                parens += 1
            elif ch in ")]":
                parens = max(0, parens - 1)
            elif parens and not seen:
                continue  # braces inside the signature: destructuring, inline types
            elif ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
                if seen and depth <= 0:
                    return j
        if not seen and (j - start >= 2 or lines[j].rstrip().endswith((";", ","))):
            return j if lines[j].rstrip().endswith(";") else start
    return len(lines) - 1


N = r"(?P<name>[A-Za-z_$][\w$]*)"
JS = [("function", rf"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*{N}"),
      ("class", rf"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+{N}"),
      ("function", rf"^\s*(?:export\s+)?(?:const|let|var)\s+{N}\s*(?::[^=]+)?=\s*(?:async\s*)?"
                   rf"(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*(?::[^=]+)?=>"),
      ("function", rf"^\s*(?:export\s+)?(?:const|let|var)\s+{N}\s*=\s*(?:async\s+)?function\b"),
      ("type", rf"^\s*(?:export\s+)?(?:declare\s+)?(?:interface|type|enum)\s+{N}"),
      ("method", rf"^\s+(?:(?:static|async|get|set|public|private|protected|readonly|override)\s+)*"
                 rf"{N}\s*(?:<[^>]*>)?\([^)]*\)?\s*(?::\s*[^{{]+)?\{{(?:.*\}})?\s*$")]
LANGS: dict[str, list[tuple[str, str]]] = {
    "js": JS,
    "go": [("function", r"^func\s+(?:\((?P<recv>[^)]*)\)\s*)?(?P<name>\w+)\s*[\[(]"),
           ("type", r"^type\s+(?P<name>\w+)\s")],
    "rs": [("function", r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:(?:async|const|unsafe)\s+|extern\s+\"[^\"]*\"\s+)*fn\s+(?P<name>\w+)"),
           ("type", r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait|union|mod)\s+(?P<name>\w+)"),
           ("impl", r"^\s*impl(?:<[^>]*>)?\s+(?:[\w:]+(?:<[^>]*>)?\s+for\s+)?(?P<name>[\w:]+)")],
    "class_langs": [("class", r"^\s*(?:[\w@]+\s+)*(?:class|interface|enum|record|struct|object|trait|protocol|"
                              r"extension|mixin)\s+(?P<name>[A-Za-z_]\w*)"),
                    ("function", r"^\s*(?:[\w@]+\s+)*(?:fun|func|function)\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?"
                                 r"(?P<name>[A-Za-z_]\w*)\s*[(<]"),
                    ("function", r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|override|"
                                 r"virtual|async|sealed|synchronized|external|factory|const|inline|extern|"
                                 r"unsafe|partial|new)\s+)*(?!return\b|else\b|new\b)[\w<>\[\],.?*&:]+\s+\**"
                                 r"(?P<name>[A-Za-z_~][\w:]*)\s*\([^;]*$")],
    "rb": [("function", r"^\s*def\s+(?:self\.)?(?P<name>[\w?!]+)"),
           ("class", r"^\s*(?:class|module)\s+(?P<name>[\w:]+)")],
    "sh": [("function", r"^\s*(?:function\s+)?(?P<name>[\w-]+)\s*\(\)\s*\{")],
    "lua": [("function", r"^\s*(?:local\s+)?function\s+(?P<name>[\w.:]+)")],
}
LANG_OF = {**{e: "js" for e in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")},
           ".go": "go", ".rs": "rs", ".rb": "rb", ".sh": "sh", ".lua": "lua", ".py": "py",
           **{e: "class_langs" for e in (".java", ".kt", ".kts", ".cs", ".dart", ".swift", ".c", ".h",
                                         ".cc", ".cpp", ".hpp", ".ino", ".php", ".scala", ".m", ".mm")}}
COMPILED = {k: [(kind, re.compile(rx)) for kind, rx in v] for k, v in LANGS.items()}
IMPORT_RES = {
    "js": [r"import\s+(?:type\s+)?(?:[^'\"]*?\sfrom\s+)?['\"]([^'\"]+)['\"]", r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
           r"import\(\s*['\"]([^'\"]+)['\"]", r"export\s+[^'\"]*?\sfrom\s+['\"]([^'\"]+)['\"]"],
    "go": [r"^\s*(?:import\s+)?(?:[\w.]+\s+)?\"([\w./-]+)\"\s*$"],
    "rs": [r"^\s*(?:pub\s+)?mod\s+(\w+)\s*;", r"^\s*(?:pub\s+)?use\s+crate::([\w:]+)"],
    "class_langs": [r"^\s*import\s+(?:static\s+)?['\"]?([\w./:-]+)['\"]?", r"#include\s+\"([^\"]+)\"",
                    r"(?:require|include)(?:_once)?\s*\(?\s*['\"]([^'\"]+)['\"]"],
    "rb": [r"require_relative\s+['\"]([^'\"]+)['\"]"],
    "sh": [r"^\s*(?:source|\.)\s+['\"]?([\w./-]+)"],
    "lua": [r"require\s*\(?\s*['\"]([\w./-]+)['\"]"],
}
PURPOSE_SKIP = re.compile(r"(?i)copyright|license|spdx|eslint|@ts-|prettier|^!|use strict|^-\*-|"
                          r"auto-?generated|do not edit|^#!|^\s*$|^package\s|^import\s|^@")


def purpose_from_comments(lines: list[str]) -> str:
    for line in lines[:40]:
        s = line.strip()
        m = re.match(r"^(?://[/!]?|#|\*|/\*\*?|--|;)\s*(.*?)\s*(?:\*/)?$", s)
        if not m:
            if s and not PURPOSE_SKIP.search(s):
                break
            continue
        text = m.group(1).strip()
        if text and not PURPOSE_SKIP.search(text) and len(text) > 8:
            return re.sub(r"^Package \w+ ", "", text)[:140]
    return ""


def parse_python(text: str, lines: list[str]) -> tuple[list, list, str]:
    tree = ast.parse(text)
    syms, imports = [], []

    def add(node, prefix=""):
        start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
        kind = "class" if isinstance(node, ast.ClassDef) else ("method" if prefix else "function")
        syms.append([kind, prefix + node.name, start, node.end_lineno, lines[node.lineno - 1].strip()[:120]])

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add(node)
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        add(child, node.name + ".")
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.end_lineno - node.lineno >= 3:
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name) and target.id.isupper():
                syms.append(["const", target.id, node.lineno, node.end_lineno, lines[node.lineno - 1].strip()[:120]])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            imports.append(base)
            if node.module is None or node.level:
                imports += [base.rstrip(".") + "." + a.name if node.module else "." * node.level + a.name
                            for a in node.names]
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    return syms, imports, (doc[0][:140] if doc else purpose_from_comments(lines))


def parse_generic(lang: str, lines: list[str]) -> tuple[list, list, str]:
    syms = []
    for i, line in enumerate(lines):
        if len(line) > 400:
            continue
        for kind, rx in COMPILED[lang]:
            m = rx.match(line)
            if not m:
                continue
            name = m.group("name")
            if name in KEYWORDS or name.isdigit():
                continue
            if lang == "go" and m.groupdict().get("recv"):
                parts = m.group("recv").split()
                recv = re.sub(r"\[.*", "", re.sub(r"[*\s]", "", parts[-1] if parts else ""))
                name, kind = f"{recv}.{name}", "method"
            if lang in ("rb", "lua", "sh"):
                end = i
            else:
                end = block_end(lines, i)
            syms.append([kind, name, i + 1, end + 1, line.strip()[:120]])
            break
    if lang in ("rb", "lua"):  # no braces: a symbol runs until the next one at the same or lower indent
        for k, s in enumerate(syms):
            indent = len(lines[s[2] - 1]) - len(lines[s[2] - 1].lstrip())
            nxt = next((t[2] - 1 for t in syms[k + 1:]
                        if len(lines[t[2] - 1]) - len(lines[t[2] - 1].lstrip()) <= indent), len(lines))
            s[3] = max(s[2], nxt)
    # qualify members with their container (innermost enclosing class/impl/type)
    containers = [s for s in syms if s[0] in ("class", "impl", "type")]
    for s in syms:
        if "." in s[1] or s[0] in ("class", "impl", "type"):
            continue
        parent = [c for c in containers if c[2] < s[2] <= c[3]]
        if parent:
            p = max(parent, key=lambda c: c[2])
            s[1], s[0] = f"{p[1].split('::')[-1]}.{s[1]}", "method"
    text = "\n".join(lines)
    imports = []
    for rx in IMPORT_RES.get(lang, []):
        imports += re.findall(rx, text, re.M)
    if lang == "go":
        imports = [i for block in re.findall(r"import\s*\((.*?)\)", text, re.S) for i in re.findall(r"\"([^\"]+)\"", block)] \
            + re.findall(r"^import\s+(?:[\w.]+\s+)?\"([^\"]+)\"", text, re.M)
    return syms, sorted(set(imports)), purpose_from_comments(lines)


def parse_other(path: str, lines: list[str]) -> str:
    if path.endswith(".md"):
        return next((l.lstrip("# ").strip()[:140] for l in lines if l.startswith("#")), "")
    if path.endswith("package.json") or path.endswith("composer.json"):
        try:
            return (json.loads("\n".join(lines)).get("description") or "")[:140]
        except (json.JSONDecodeError, AttributeError):
            return ""
    return purpose_from_comments(lines)


def is_generated(lines: list[str]) -> bool:
    head = "\n".join(lines[:8]).lower()
    return ("generated" in head and ("do not edit" in head or "@generated" in head or "auto-generated" in head)) \
        or (len(lines) < 5 and sum(map(len, lines)) > 5000)


def parse_file(repo: Path, rel: str) -> dict:
    p = repo / rel
    raw = p.read_bytes()
    entry = {"hash": hashlib.sha1(raw).hexdigest(), "size": len(raw), "symbols": [], "imports": [],
             "purpose": "", "lines": 0}
    if b"\0" in raw[:4000] or len(raw) > 1_500_000:
        entry["kind"] = "binary/large"
        return entry
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    entry["lines"] = len(lines)
    ext = p.suffix.lower()
    if is_generated(lines):
        entry["kind"] = "generated"
        entry["purpose"] = "generated file - edit its source instead"
        return entry
    lang = LANG_OF.get(ext)
    entry["kind"] = lang or "other"
    try:
        if lang == "py":
            entry["symbols"], entry["imports"], entry["purpose"] = parse_python(text, lines)
        elif lang:
            entry["symbols"], entry["imports"], entry["purpose"] = parse_generic(lang, lines)
        else:
            entry["purpose"] = parse_other(rel, lines)
    except (SyntaxError, ValueError, RecursionError):
        entry["symbols"], entry["imports"], entry["purpose"] = parse_generic("class_langs", lines)
    entry["shape"] = hashlib.sha1(json.dumps([[s[0], s[1]] for s in entry["symbols"]] +
                                             sorted(entry["imports"])).encode()).hexdigest()[:12]
    return entry


# ------------------------------------------------------------------ import resolution
class Resolver:
    JS_EXT = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte", ".d.ts",
              "/index.ts", "/index.tsx", "/index.js", "/index.jsx"]

    def __init__(self, repo: Path, files: set[str]):
        self.files = files
        self.by_tail: dict[str, list[str]] = {}
        for f in files:
            parts = f.split("/")
            for k in range(1, min(len(parts), 6) + 1):
                self.by_tail.setdefault("/".join(parts[-k:]), []).append(f)
        self.go_mods = {}
        for f in files:
            if f.endswith("go.mod"):
                m = re.search(r"^module\s+(\S+)", (repo / f).read_text(errors="replace"), re.M)
                if m:
                    self.go_mods[m.group(1)] = self.dir_of(f)
        self.dart_pkgs = {}
        for f in files:
            if f.endswith("pubspec.yaml"):
                m = re.search(r"^name:\s*(\S+)", (repo / f).read_text(errors="replace"), re.M)
                if m:
                    base = str(Path(f).parent)
                    self.dart_pkgs[m.group(1)] = "lib" if base == "." else f"{base}/lib"

    @staticmethod
    def dir_of(f: str) -> str:
        d = str(Path(f).parent).replace("\\", "/")
        return "" if d == "." else d

    @staticmethod
    def norm(path: str) -> str:
        n = os.path.normpath(path.lstrip("/")).replace("\\", "/")
        return "" if n == "." else n

    def first(self, candidates) -> list[str]:
        for c in candidates:
            c = self.norm(c)
            if c in self.files:
                return [c]
        return []

    def resolve(self, src: str, spec: str, kind: str) -> list[str]:
        d = str(Path(src).parent)
        d = "" if d == "." else d
        if kind == "js":
            if spec.startswith("."):
                return self.first(f"{d}/{spec}{e}" for e in self.JS_EXT)
            if spec.startswith(("@/", "~/")):
                return self.first(f"{root}{spec[2:]}{e}" for root in ("src/", "", "app/") for e in self.JS_EXT)
            return []
        if kind == "py":
            level = len(spec) - len(spec.lstrip("."))
            mod = spec.lstrip(".").replace(".", "/")
            if level:
                base = Path(src).parent
                for _ in range(level - 1):
                    base = base.parent
                b = "" if str(base) == "." else f"{base}/"
                return self.first([f"{b}{mod}.py", f"{b}{mod}/__init__.py"] if mod else [f"{b}__init__.py"])
            hits = self.by_tail.get(f"{mod}.py", []) + self.by_tail.get(f"{mod}/__init__.py", [])
            return sorted(hits)[:1]
        if kind == "go":
            for mod, base in self.go_mods.items():
                if spec == mod or spec.startswith(mod + "/"):
                    target = self.norm(f"{base}/{spec[len(mod):]}")
                    return sorted(f for f in self.files if self.dir_of(f) == target
                                  and f.endswith(".go") and not f.endswith("_test.go"))[:20]
            return []
        if kind == "rs":
            if "::" not in spec:
                return self.first([f"{d}/{spec}.rs", f"{d}/{spec}/mod.rs"])
            first = spec.split("::")[0]
            return sorted(self.by_tail.get(f"{first}.rs", []) + self.by_tail.get(f"{first}/mod.rs", []))[:1]
        if kind == "class_langs":
            if spec.startswith("package:"):
                pkg, _, rest = spec[8:].partition("/")
                return self.first([f"{self.dart_pkgs.get(pkg, '-')}/{rest}"])
            if "/" in spec or spec.endswith((".h", ".hpp", ".dart", ".php")):
                return self.first([f"{d}/{spec}", spec]) or sorted(self.by_tail.get(spec.lstrip("./"), []))[:1]
            path = spec.replace(".", "/")
            for ext in (".java", ".kt", ".scala", ".swift", ".cs"):
                hits = self.by_tail.get(path + ext) or self.by_tail.get("/".join(path.split("/")[-2:]) + ext)
                if hits:
                    return sorted(hits)[:1]
            return []
        if kind in ("rb", "lua", "sh"):
            spec = spec if spec.endswith((".rb", ".lua", ".sh")) else spec + {"rb": ".rb", "lua": ".lua", "sh": ""}[kind]
            return self.first([f"{d}/{spec}", spec])
        return []


# ------------------------------------------------------------------ index store
class CodeMap:
    def __init__(self, repo: Path):
        self.repo = repo
        self.dir = repo / ".claude" / "code-map"
        self.index_path = self.dir / "index.json"
        self.notes_path = self.dir / "notes.json"
        self.data = {"version": VERSION, "files": {}}
        if self.index_path.exists():
            try:
                loaded = json.loads(self.index_path.read_text())
                if loaded.get("version") == VERSION:
                    self.data = loaded
            except (json.JSONDecodeError, OSError):
                pass
        self.notes = json.loads(self.notes_path.read_text()) if self.notes_path.exists() else {}

    def list_files(self) -> list[str]:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=self.repo,
                             capture_output=True)
        if out.returncode == 0:
            paths = [p for p in out.stdout.decode("utf-8", errors="replace").split("\0") if p]
        else:
            paths = []
            for dp, dns, fns in os.walk(self.repo):
                dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
                paths += [str((Path(dp) / f).relative_to(self.repo)).replace("\\", "/") for f in fns]
        keep = []
        for p in paths:
            parts = p.split("/")
            if any(x in SKIP_DIRS for x in parts[:-1]) or p.startswith(".claude/code-map/") or SKIP_FILES.search(p):
                continue
            name, ext = parts[-1], Path(p).suffix.lower()
            if ext in CODE_EXT or ext in OTHER_EXT or name in OTHER_NAMES:
                keep.append(p)
        return keep

    def update(self, full: bool = False) -> dict:
        t0 = time.time()
        files = self.data["files"]
        current = self.list_files()
        changed, added, removed = [], [], []
        live = set()
        for rel in current:
            try:
                st = (self.repo / rel).stat()
            except OSError:
                continue  # deleted in the working tree but still in the git index
            live.add(rel)
            old = files.get(rel)
            stamp = [st.st_mtime_ns, st.st_size]
            if not full and old and old.get("stamp") == stamp:
                continue
            if not full and old and old.get("size") == st.st_size:
                h = hashlib.sha1((self.repo / rel).read_bytes()).hexdigest()
                if h == old.get("hash"):
                    old["stamp"] = stamp
                    continue
            try:
                entry = parse_file(self.repo, rel)
            except OSError:
                continue
            entry["stamp"] = stamp
            (changed if old else added).append(rel)
            files[rel] = entry
        for rel in list(files):
            if rel not in live:
                removed.append(rel)
                del files[rel]
        if changed or added or removed or full or "deps_done" not in self.data:
            # added/removed files can change how other files' imports resolve: redo all then
            self.resolve_deps(changed if changed and not (added or removed or full) and "deps_done" in self.data else None)
            self.data["deps_done"] = True
            self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.save()
        return {"changed": changed, "added": added, "removed": removed, "seconds": round(time.time() - t0, 2)}

    def resolve_deps(self, only: list[str] | None) -> None:
        files = self.data["files"]
        resolver = Resolver(self.repo, set(files))
        for rel in (only if only is not None else list(files)):
            e = files.get(rel)
            if not e:
                continue
            kind = e.get("kind")
            deps = set()
            for spec in e.get("imports", []):
                deps.update(resolver.resolve(rel, spec, kind))
            deps.discard(rel)
            e["deps"] = sorted(deps)

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        gi = self.dir / ".gitignore"
        if not gi.exists():
            gi.write_text("# generated by code_map.py; notes.json is meant to be committed\nindex.json\nMAP.md\n")
        self.index_path.write_text(json.dumps(self.data, separators=(",", ":")))
        (self.dir / "MAP.md").write_text(self.render_summary(None, 10))

    def save_notes(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.notes_path.write_text(json.dumps(self.notes, indent=1, sort_keys=True, ensure_ascii=False) + "\n")

    # -------------------------------------------------------------- queries
    def note_for(self, rel: str) -> tuple[str, bool]:
        n = self.notes.get(rel)
        if not n:
            return "", False
        e = self.data["files"].get(rel)
        stale = bool(e and n.get("shape") and n["shape"] != e.get("shape"))
        return n["text"], stale

    def render_summary(self, path: str | None, max_symbols: int) -> str:
        files = self.data["files"]
        sel = sorted(f for f in files if not path or f == path or f.startswith(path.rstrip("/") + "/"))
        nsym = sum(len(files[f]["symbols"]) for f in sel)
        out = [f"# Code map{(' of ' + path) if path else ''}: {len(sel)} files, {nsym} symbols "
               f"(updated {self.data.get('updated', '?')})",
               "Use this instead of opening files. Then `find`/`show`/`refs` and Read only the listed ranges.",
               "Legend: (N L) = lines; name:start-end; [STALE NOTE] = file changed shape since note was written.", ""]
        by_dir: dict[str, list[str]] = {}
        for f in sel:
            by_dir.setdefault(str(Path(f).parent).replace("\\", "/"), []).append(f)
        for key in self.notes:  # noted directories that only contain sub-directories
            d = key.rstrip("/")
            if key.endswith("/") and d not in by_dir and any(f.startswith(key) for f in sel):
                by_dir[d] = []
        for d in sorted(by_dir):
            dkey = "" if d == "." else d + "/"
            dnote = (self.notes.get(dkey) or {}).get("text", "")
            out.append(f"## {dkey or './'}" + (f" - {dnote}" if dnote else ""))
            for f in by_dir[d]:
                e = files[f]
                note, stale = self.note_for(f)
                desc = note or e.get("purpose", "")
                tag = " [STALE NOTE]" if stale else ""
                head = f"- {Path(f).name} ({e.get('lines', 0)} L)" + (f" - {desc}" if desc else "") + tag
                out.append(head)
                syms = [s for s in e["symbols"] if s[0] != "method"] or e["symbols"]
                if syms:
                    shown = ", ".join(f"{s[1]}:{s[2]}-{s[3]}" for s in syms[:max_symbols])
                    more = len(e["symbols"]) - min(len(syms), max_symbols)
                    out.append(f"    {shown}" + (f" (+{more} more: show {f})" if more > 0 else ""))
            out.append("")
        return "\n".join(out)

    def find(self, query: str, kind: str | None, limit: int) -> list[str]:
        q = query.lower()
        scored = []
        for f, e in self.data["files"].items():
            for s in e["symbols"]:
                if kind and s[0] != kind:
                    continue
                name = s[1].lower()
                short = name.split(".")[-1]
                if short == q or name == q:
                    score = 0
                elif short.startswith(q) or name.startswith(q):
                    score = 1
                elif q in name:
                    score = 2
                elif re.search(".*".join(map(re.escape, q)), name):
                    score = 4
                else:
                    continue
                scored.append((score, len(name), f, f"{f}:{s[2]}-{s[3]}  {s[0]} {s[1]}    | {s[4]}"))
            if not kind:
                note, _ = self.note_for(f)
                hay = f"{f} {e.get('purpose', '')} {note}".lower()
                if q in hay:
                    scored.append((3, len(f), f, f"{f}  (file, {e.get('lines', 0)} L) - {note or e.get('purpose', '')}"))
        scored.sort(key=lambda t: (t[0], t[1], t[2]))
        return [s[3] for s in scored[:limit]]

    def enclosing(self, rel: str, line: int) -> str:
        e = self.data["files"].get(rel)
        if not e:
            return ""
        hits = [s for s in e["symbols"] if s[2] <= line <= s[3]]
        if not hits:
            return "(top level)"
        s = max(hits, key=lambda s: s[2])
        return f"{s[1]}:{s[2]}-{s[3]}"

    def refs(self, name: str, limit: int) -> list[str]:
        out = subprocess.run(["git", "grep", "-n", "-w", "-I", "-F", "--untracked", "-e", name.split(".")[-1]],
                             cwd=self.repo, capture_output=True, text=True, errors="replace")
        rows, defs = [], set()
        for f, e in self.data["files"].items():
            for s in e["symbols"]:
                if s[1] == name or s[1].split(".")[-1] == name.split(".")[-1]:
                    defs.add((f, s[2]))
        grouped: dict[str, list[str]] = {}
        for line in out.stdout.splitlines():
            m = re.match(r"(.+?):(\d+):(.*)", line)
            if not m or m.group(1).startswith(".claude/code-map/"):
                continue
            f, ln, text = m.group(1), int(m.group(2)), m.group(3).strip()
            tag = "DEF " if (f, ln) in defs else ""
            grouped.setdefault(f, []).append(f"  {ln:>5}  {tag}in {self.enclosing(f, ln)}  | {text[:100]}")
        for f in sorted(grouped, key=lambda f: (-len(grouped[f]), f)):
            rows.append(f"{f} ({len(grouped[f])})")
            rows += grouped[f][:12] + ([f"  ... {len(grouped[f]) - 12} more"] if len(grouped[f]) > 12 else [])
            if len(rows) >= limit:
                rows.append("... (limit reached; narrow the name or use --limit)")
                break
        return rows

    def reverse_deps(self) -> dict[str, list[str]]:
        rev: dict[str, list[str]] = {}
        for f, e in self.data["files"].items():
            for d in e.get("deps", []):
                rev.setdefault(d, []).append(f)
        return rev


# ------------------------------------------------------------------ cli
def find_repo(start: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 else start


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary"); s.add_argument("--path"); s.add_argument("--max-symbols", type=int, default=10)
    s = sub.add_parser("find"); s.add_argument("query"); s.add_argument("--kind"); s.add_argument("--limit", type=int, default=25)
    s = sub.add_parser("show"); s.add_argument("path")
    s = sub.add_parser("refs"); s.add_argument("name"); s.add_argument("--limit", type=int, default=80)
    s = sub.add_parser("deps"); s.add_argument("path"); s.add_argument("--depth", type=int, default=1)
    s = sub.add_parser("note"); s.add_argument("path"); s.add_argument("text")
    sub.add_parser("stale"); sub.add_parser("update"); sub.add_parser("build"); sub.add_parser("stats")
    args = ap.parse_args()

    repo = (args.repo or find_repo(Path.cwd())).resolve()
    cm = CodeMap(repo)
    res = cm.update(full=args.cmd == "build")
    delta = len(res["changed"]) + len(res["added"]) + len(res["removed"])
    if delta and args.cmd not in ("update", "build"):
        print(f"(map refreshed: {len(res['changed'])} changed, {len(res['added'])} added, "
              f"{len(res['removed'])} removed)", file=sys.stderr)
    files = cm.data["files"]

    def rel_arg(p: str) -> str:
        cand = Path(p)
        if cand.is_absolute():
            try:
                return str(cand.resolve().relative_to(repo)).replace("\\", "/")
            except ValueError:
                return p
        full = (Path.cwd() / cand).resolve()
        try:
            r = str(full.relative_to(repo)).replace("\\", "/")
            return r if r in files or (repo / r).is_dir() else p.strip("./") or p
        except ValueError:
            return p

    if args.cmd in ("update", "build"):
        print(f"code-map {args.cmd}: {len(files)} files indexed; {len(res['changed'])} changed, "
              f"{len(res['added'])} added, {len(res['removed'])} removed in {res['seconds']}s")
    elif args.cmd == "stats":
        nsym = sum(len(e["symbols"]) for e in files.values())
        stale = [f for f in cm.notes if cm.note_for(f)[1]]
        print(f"{len(files)} files, {nsym} symbols, {len(cm.notes)} notes ({len(stale)} stale), "
              f"MAP.md ~{len((cm.dir / 'MAP.md').read_text()) // 4} tokens; updated {cm.data.get('updated')}")
    elif args.cmd == "summary":
        print(cm.render_summary(args.path.strip("/") if args.path else None, args.max_symbols))
    elif args.cmd == "find":
        rows = cm.find(args.query, args.kind, args.limit)
        print("\n".join(rows) if rows else f"no symbol/file matches '{args.query}' (try refs, or a shorter query)")
    elif args.cmd == "show":
        rel = rel_arg(args.path)
        e = files.get(rel)
        if not e:
            print(f"{rel}: not in map (unsupported type, ignored, or wrong path)")
            return 1
        note, stale = cm.note_for(rel)
        rev = cm.reverse_deps().get(rel, [])
        print(f"{rel}  ({e.get('lines', 0)} lines, {e.get('kind')})")
        if note or e.get("purpose"):
            print(f"purpose: {note or e['purpose']}" + ("  [STALE NOTE: re-check and update]" if stale else ""))
        if e.get("deps"):
            print("imports: " + ", ".join(e["deps"]))
        if rev:
            print(f"imported by ({len(rev)}): " + ", ".join(sorted(rev)[:15]) + (" ..." if len(rev) > 15 else ""))
        for k, n, a, b, sig in e["symbols"]:
            print(f"  {a:>5}-{b:<5} {k:<8} {n}    | {sig}")
        if not e["symbols"]:
            print("  (no symbols: read it directly if needed)")
    elif args.cmd == "refs":
        rows = cm.refs(args.name, args.limit)
        print("\n".join(rows) if rows else f"no references to '{args.name}'")
    elif args.cmd == "deps":
        rel = rel_arg(args.path)
        if rel not in files:
            print(f"{rel}: not in map")
            return 1
        rev = cm.reverse_deps()
        fwd, back, frontier_f, frontier_b = set(), set(), {rel}, {rel}
        for _ in range(max(1, args.depth)):
            frontier_f = {d for f in frontier_f for d in files.get(f, {}).get("deps", [])} - fwd - {rel}
            frontier_b = {d for f in frontier_b for d in rev.get(f, [])} - back - {rel}
            fwd |= frontier_f
            back |= frontier_b
        print(f"{rel} imports ({len(fwd)}):\n  " + ("\n  ".join(sorted(fwd)) or "-"))
        print(f"imported by / affected if changed ({len(back)}):\n  " + ("\n  ".join(sorted(back)) or "-"))
    elif args.cmd == "note":
        rel = args.path if args.path.endswith("/") else rel_arg(args.path)
        if not rel.endswith("/") and rel not in files:
            print(f"{rel}: not in map; for a directory end the path with /")
            return 1
        cm.notes[rel] = {"text": args.text.strip(), "shape": files.get(rel, {}).get("shape")}
        cm.save_notes()
        (cm.dir / "MAP.md").write_text(cm.render_summary(None, 10))
        print(f"note saved for {rel}")
    elif args.cmd == "stale":
        stale = [f for f in sorted(cm.notes) if cm.note_for(f)[1]]
        missing = [f for f in sorted(cm.notes) if not f.endswith("/") and f not in files]
        for f in stale:
            print(f"STALE   {f}: {cm.notes[f]['text']}")
        for f in missing:
            print(f"GONE    {f}: file no longer exists (remove or move the note)")
        if not stale and not missing:
            print("all notes current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
