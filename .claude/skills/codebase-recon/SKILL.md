---
name: codebase-recon
description: Find exactly where a change belongs before editing - detect the stack(s) and the project's real lint/test/build commands, map entry points, trace call sites, find existing helpers and conventions. Use at the start of any task in an unfamiliar or multi-project repo, before adding any new function/file/dependency, when asked "where is X handled", or whenever you are unsure which file to touch.
---

# Codebase Recon

Goal: name the exact file:line to change, the existing code to reuse, and the
commands that prove it works, with the fewest reads possible.

## Step 1 - Stack and commands (one command)
```bash
python3 .claude/skills/codebase-recon/scripts/detect_stack.py [repo] [--json]
```
Reports every project root (monorepos included), package manager, and the
install/format/lint/typecheck/build/test commands **the project defines**
(package.json scripts, pyproject tools, gradlew, Makefile, CI workflows).
CI `run:` lines are listed as canonical: when they disagree with a guess, CI wins.
Read every instruction file it lists (CLAUDE.md, AGENTS.md, CONTRIBUTING.md) - they override defaults.

## Step 2 - Locate, narrowing fast
Run independent searches in parallel. Order of precision:
1. **Exact strings the user/issue mentions** - error text, UI label, route,
   log line, config key: `Grep` for them literally. Fastest path to the code.
2. **Symbol definitions**: `Grep "def name|function name|func name|class Name|fun name"`.
3. **Call sites / blast radius**: `Grep -w name` across the repo, including
   tests, configs, templates, string-based lookups (`"name"`, `'name'`) and
   other languages in the repo (e.g. firmware <-> app protocol fields).
4. **History of the area**: `git log --oneline -10 -- <path>`, `git log -S'<snippet>'`
   to learn why code looks the way it does before changing it.
Use the `Explore` agent only for genuinely broad sweeps; for 1-3 known terms, grep directly.

## Step 3 - Read the minimum, but read it fully
- Read the target function **and** its callers and its tests. Partial reads cause
  wrong-place edits.
- For large files read the relevant range (offset/limit), not the whole file.
- Find one existing example of the same kind of thing (another endpoint,
  screen, command handler) - it is the template for style, error handling,
  logging, naming, file placement and test layout.

## Step 4 - Reuse check (before writing anything new)
Search for an existing helper/util/hook/service that already does the job:
```
Grep -i "<verb><noun>|<noun>_<verb>|format|parse|validate|retry|debounce" in utils/, lib/, common/, shared/, helpers/
```
If one exists: use or extend it. If two near-duplicates exist: use the newer/
more-used one and note the duplication as a follow-up (or remove it if in scope).

## Step 5 - Write the recon note (3-6 lines)
```
Change at:  src/net/client.ts:142 (sendCommand)  + callers: hud.ts:88, bridge.ts:31
Reuse:      retryWithBackoff() in src/util/retry.ts
Pattern:    mirror src/net/telemetry.ts (same error/log style)
Tests:      src/net/__tests__/client.test.ts  (run: npm test -- client)
Checks:     npm run lint, npm run typecheck, npm test
```
Exit gate: you can point at the exact lines and you know which test command
covers them. If not, you are not done with recon.

## Pitfalls that cause wrong-place edits
- Generated files (`*.g.dart`, `*_pb2.py`, `dist/`, `build/`, files headed
  "DO NOT EDIT"): edit the source/schema and regenerate instead.
- Duplicated code paths (web + mobile, debug + release, v1 + v2 API): check
  whether the change must land in all of them.
- Vendored/third-party copies: never patch in place unless the repo does so already.
- Same name in several modules: confirm the import path actually used at runtime.
