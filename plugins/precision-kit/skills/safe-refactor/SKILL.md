---
name: safe-refactor
description: Restructure code (rename, extract, move, split files, dedupe, change signatures, replace a pattern) while provably preserving behaviour. Use for any refactor, rename, file move, API signature change, deduplication or "clean up this module" request, and whenever a change touches many call sites.
---

# Safe Refactor

Refactor = structure changes, behaviour does not. Prove the "does not".

## 1. Lock behaviour first
- Identify tests that cover the code. If coverage is thin, write
  **characterization tests** that pin current outputs (including odd ones)
  before changing anything. Commit-worthy on their own.
- Run the baseline: the `verification-gate` skill (`verify.py --changed`)
  (or the targeted test command). Record failures that pre-exist.

## 2. Map the blast radius
`Grep -w <symbol>` across the whole repo, plus string uses, re-exports,
dynamic imports, docs and other languages (protocol field names shared
between programs, JSON keys, DB columns, env var names). List every call site; this
list is your checklist.

## 3. Change in small, verifiable steps
One mechanical transformation at a time, checks green after each:
1. Introduce the new shape (new function/module) alongside the old.
2. Migrate call sites (all of them - work the checklist).
3. Delete the old shape (no wrappers/aliases left behind unless it is public
   API that needs a deprecation period).
Prefer tool-assisted, exact edits: `Edit` with `replace_all` for a unique
identifier, LSP/IDE rename, `gofmt -r`, `sed` with word boundaries - then grep
again to confirm zero old references remain.

## 4. Rules
- Never mix refactor and behaviour change in one step. If you find a bug,
  note it; fix it in a separate commit with its own test.
- Keep public signatures stable unless the task says otherwise.
- Moving files: update imports, build configs, test paths, docs, CODEOWNERS;
  use `git mv` so history follows.
- Don't reformat untouched code (noise hides the real diff).

## 5. Done when
- Old symbol/path: `Grep` finds 0 references.
- Same tests pass as at baseline (+ new characterization tests).
- `git diff --stat` shows only intended files.
