---
name: precision-workflow
description: Master workflow for ANY software task in any project - feature, bug fix, refactor, cleanup, upgrade, live modernization, new project, CI, docs, performance, migration, UI change, PR feedback, or a question about code. Use it at the start of every such task, even small ones, before touching a file. It routes to the specialised precision-kit skills and defines the gates a change must pass before it is called done.
---

# Precision Workflow

One pipeline for every change. Each phase has an exit gate; do not start the
next phase until the gate is met. Scale the depth to the task, never skip a
gate: a one-line fix still gets located precisely, verified and self-reviewed.

## Route by task type (from `task-intake`)

| Task | Primary skills (in order) |
|------|---------------------------|
| Question / explain / "where is" | `codebase-qa` (no code changes) |
| Bug, crash, failing test/CI | `root-cause-debug` -> `test-strategy` |
| Feature / integration | `modern-integration` -> `test-strategy` -> `legacy-cleanup` |
| Refactor / rename / move | `safe-refactor` -> `legacy-cleanup` |
| Remove old code | `legacy-cleanup` |
| Dependency / SDK / toolchain | `dependency-upgrade` |
| "Is it up to date?", maintenance, outdated/vulnerable deps, deprecated APIs | `live-modernize` -> `dependency-upgrade` |
| Brand-new project or package | `new-project-bootstrap` -> `ci-setup` |
| Slow / heavy | `performance-optimize` |
| Schema / data change | `database-migration` |
| UI / visual change | implement -> `ui-verify` |
| CI / pipelines / releases | `ci-setup` |
| Docs | `docs-sync` |
| PR review comments / red checks | `pr-feedback` |
Always on: `efficiency-guard` (start), `codebase-recon` (before edits),
`verification-gate` + `secret-scan` + `self-review` (before commit),
`docs-sync` + `project-memory` (when behaviour or setup changed), `git-delivery` (end).

## Phase gates

| # | Phase | Skill | Exit gate |
|---|-------|-------|-----------|
| 0 | Budget | `efficiency-guard` | Task sized (S/M/L), stop condition known |
| 1 | Intake | `task-intake` | Acceptance criteria written; assumptions stated |
| 2 | Recon | `codebase-recon` | Exact files/lines named; conventions + check commands known |
| 3 | Baseline | `verification-gate` | Checks run BEFORE editing; pre-existing failures recorded |
| 4 | Plan | (this file) | Smallest diff meeting every criterion; blast radius listed |
| 5 | Implement | routed skills above | Project idiom, current APIs, no guessing |
| 6 | Clean | `legacy-cleanup` | Code made obsolete by this change removed |
| 7 | Test | `test-strategy` (+ `ui-verify`) | Each criterion has a test that fails without the change |
| 8 | Verify | `verification-gate`, `secret-scan` | Verdict PASS (every SKIP/FAIL explained); no secrets |
| 9 | Review | `self-review` | Diff read line by line; checklist clean |
| 10 | Deliver | `git-delivery`, `project-memory` | Committed, pushed, honest report; memory updated if learned something |

## Sizing (decides depth, not whether a phase happens)
- **S** - one file, obvious location, < ~30 lines: phases 1-2 take a minute;
  targeted test + lint of that project only.
- **M** - several files in one module or a new feature: full pipeline, short
  plan in the task list.
- **L** - cross-module, schema/API change, upgrade, unclear root cause: full
  pipeline, plan checked against acceptance criteria before phase 5,
  reviewable commits.

## Fast start (one message, parallel)
- Run `detect_stack.py` from the `codebase-recon` skill (stacks + exact commands).
- `git status --short && git log --oneline -5`.
- Read CLAUDE.md / AGENTS.md / CONTRIBUTING.md if present.

## Non-negotiable rules
1. **Locate before you write.** Never edit a file you haven't read; search for
   an existing helper before adding one.
2. **Baseline before you change.** Know pre-existing failures up front.
3. **Replace, don't accumulate.** New code that supersedes old code removes it
   in the same change.
4. **Minimal diff.** No drive-by reformatting or out-of-scope "improvements";
   they go to Follow-ups.
5. **Evidence over belief.** "Done" = a command ran and passed. Report
   SKIP/FAIL verbatim; never "should work".
6. **Stop on surprise.** If reality contradicts the plan, go back to recon.
7. **Ask only what only the user can decide** (product behaviour, destructive
   or irreversible actions, public API shape) - once, with a recommendation.

## Final report template (in the user's language)
```
What changed: <1-3 bullets, file:line links>
Why: <root cause or requirement>
Removed: <obsolete code deleted, or "none">
Verified: <commands run + verdict; tests added>
Not verified / skipped: <checks that could not run and why>
Follow-ups (out of scope): <issues noticed, not fixed>
```
