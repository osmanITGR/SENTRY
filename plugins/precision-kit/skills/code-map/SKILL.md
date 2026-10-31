---
name: code-map
description: Stop re-reading whole files and whole projects - keep a persistent, auto-updating map of the codebase (every file's purpose, every function/class/method with exact line ranges, import and reverse-import graph, call sites) and read only the line ranges a task needs. Use at the start of any task in a repository, before opening any file, whenever you are about to read a file larger than ~150 lines, when looking for where something is defined or used, when judging the impact of a change, and after editing to keep the project summary current.
---

# Code Map

Reading is the most expensive thing an agent does. The map answers "where is
it, how big is it, who uses it" in a single command of about 0.1 s, so you only
open the exact lines you need.

```bash
CM="python3 ${CLAUDE_SKILL_DIR}/scripts/code_map.py"
```

## 1. Orient once per session, without opening files
```bash
$CM summary                    # whole project: dirs, files, purposes, symbols with line ranges
$CM summary --path src/net     # large repo: only the area you work in
$CM stats                      # size of the map (MAP.md token estimate)
```
The first call builds the map (under 1 s for about 75k lines). Every later call
re-indexes **only the files that changed** (checked by mtime/size, then content
hash), including new, deleted and untracked files. The map is always current,
and you never need to rebuild it by hand.
If the summary is large (the `stats` token estimate is above about 5k), use
`--path` to show only the area you are working in.

## 2. Locate, then read only the ranges
| Need | Command | Then |
|------|---------|------|
| Where is X defined? | `$CM find X` (`--kind function|class|method|type`) | Read `path` with `offset=start-1, limit=end-start+1` (+ about 5 lines of context) |
| What is in this file? | `$CM show path` | Read only the symbols you need |
| Who uses X, and from which function? | `$CM refs X` | Read only the enclosing ranges it prints |
| What breaks if I change this file? | `$CM deps path --depth 2` | Check the reverse imports it lists |

Reading rules:
- **Default to ranged reads** (`Read` with `offset`/`limit` taken from the map).
  Read a whole file only when it is small (under ~150 lines), or you will edit
  most of it, or it has no symbols (config, docs).
- **Never re-read** a range that is already in this conversation and unchanged.
  If you are not sure it changed, `$CM show path` tells you the current line
  numbers in about 0.1 s.
- **Before an Edit**, the target range must have been read in this session.
  A ranged read is enough.
- **Line numbers move after edits.** Ask the map again (it updates itself)
  instead of guessing offsets.
- Prefer `refs` over grepping and then opening every hit: it already shows the
  enclosing function of each use.

## 3. Keep the project summary current (notes)
Mechanical facts (symbols, ranges, imports) update themselves. The
**understanding** of what a file or directory is for is stored as notes:
```bash
$CM note src/net/client.ts "Robot command API client: all HTTP goes through sendCommand (retry+timeout)"
$CM note src/net/ "Networking layer: HTTP client, WebSocket telemetry, protocol types"
$CM stale                      # notes whose file changed shape (symbols/imports) since written
```
- When you learn what a non-obvious file or directory does, write one line. The
  next session reads it in the summary instead of re-reading the code.
- After you change a file's structure (symbols or imports added, removed or
  renamed), its note shows `[STALE NOTE]`. Update it before finishing. The
  precision-kit post-edit hook reminds you automatically.
- `notes.json` is meant to be **committed** together with the change, so
  teammates and future sessions share it. `index.json` and `MAP.md` are
  regenerated and gitignored automatically.
- Notes are one-line facts, not documentation. Don't note what the file name
  or docstring already says.

## 4. Budget discipline
- Typical task: `summary --path` (once), then `find`/`refs`, then 2-6 ranged reads. If
  you are reading more than about 10 ranges for an S-sized task, stop and refine the
  query (`efficiency-guard`).
- Exploring unfamiliar code: walk the import graph with `deps` and read entry
  points first, not every file in a directory.
- Generated, minified and lock files are excluded or marked; edit their sources instead.

Supported: Python (exact, via ast), JS/TS/JSX/TSX/Vue/Svelte, Go, Rust, Java,
Kotlin, C#, Dart, Swift, C/C++/Arduino, PHP, Ruby, Scala, Lua and shell.
Config and doc files are listed with their purpose but have no symbols.
