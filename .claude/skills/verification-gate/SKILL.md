---
name: verification-gate
description: Run every lint/typecheck/build/test check the repository defines and produce an honest PASS/FAIL/UNVERIFIED verdict before anything is called done, committed or pushed. Use before claiming a task is complete, before every commit/push, to take a baseline before editing, after resolving merge conflicts, and whenever you'd otherwise write "should work".
---

# Verification Gate

"Done" is a verdict produced by commands, not a feeling.

## The command
```bash
python3 .claude/skills/verification-gate/scripts/verify.py [repo] [options]
```
| Option | Use |
|--------|-----|
| `--changed` | Only projects containing changed/untracked files (normal pre-commit use) |
| `--root web` | One project of a monorepo |
| `--only lint,test` | Subset of checks (`format,lint,typecheck,build,test`) |
| `--include-format` / `--include-install` | Add format check / dependency install |
| `--dry-run` | Show the plan without running |
| `--timeout 1800` | Per-check timeout (default 900 s) |

It discovers commands via `codebase-recon/scripts/detect_stack.py` (project
scripts first, CI-aligned), runs lint -> typecheck -> build -> test per project
and prints a table plus the tail of every failure.
Exit codes: `0` PASS, `1` FAIL, `2` UNVERIFIED (nothing could run).

## When to run
1. **Baseline** - before the first edit. Record pre-existing failures; they are
   not yours to hide and not yours to fix unless in scope.
2. **Inner loop** - the single targeted test/lint for the file you're editing
   (faster than the whole gate).
3. **Gate** - `--changed` before every commit; full run for L-sized changes,
   dependency upgrades, or changes to shared code.

## Reading the verdict
- **PASS** with SKIPs: list the skipped checks in the report (e.g. "Flutter
  build skipped: flutter not installed in this environment").
- **FAIL**: read the first error. Fix if caused by your change. If it also failed
  at baseline, say so explicitly ("pre-existing, unrelated: ...").
- **UNVERIFIED** (exit 2): you have no automated evidence. Do something else
  to verify - run the code path directly (script, REPL, curl, `run` skill),
  install the missing tool if allowed - and report exactly what was and wasn't verified.

## Beyond the script (do these when they apply)
- **Run the thing**: for CLI/server/UI changes, actually execute the changed
  path once and look at the output (the `run` skill launches apps).
- **Generated artifacts**: if the change affects codegen, schemas, lockfiles,
  migrations - regenerate and confirm the diff is clean.
- **Cross-platform**: if code has platform branches you couldn't build (Windows
  installer, Android release, firmware board), state it as unverified.
- **pre-commit**: if `.pre-commit-config.yaml` exists, run
  `pre-commit run --files $(git diff --name-only HEAD)`.

## Honesty rules
- Quote the command and its result; never paraphrase a failure as success.
- Never weaken, skip or delete checks/tests to obtain a PASS.
- "Tests pass" only if tests ran and covered the change. Lint-only PASS is
  reported as lint-only.
