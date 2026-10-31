---
name: precision-workflow
description: Master workflow for ANY code change - feature, bug fix, refactor, cleanup, upgrade, or "make it work". Use it at the start of every implementation task, even small ones, before touching a file. It routes to the specialised skills (task-intake, codebase-recon, modern-integration, legacy-cleanup, safe-refactor, root-cause-debug, test-strategy, verification-gate, self-review, efficiency-guard, dependency-upgrade, git-delivery) and defines the gates a change must pass before it is called done.
---

# Precision Workflow

One pipeline for every change. Each phase has an exit gate; do not start the
next phase until the gate is met. Scale the depth to the task, never skip a gate:
a one-line fix still gets located precisely, verified and self-reviewed.

## Phase map

| # | Phase | Skill | Exit gate |
|---|-------|-------|-----------|
| 0 | Budget | `efficiency-guard` | Task sized (S/M/L), stop conditions known |
| 1 | Intake | `task-intake` | Acceptance criteria written; ambiguities resolved or assumptions stated |
| 2 | Recon | `codebase-recon` | Exact files/lines to change named; conventions + check commands known |
| 3 | Baseline | `verification-gate` | Checks run once BEFORE editing; pre-existing failures recorded |
| 4 | Plan | (this file) | Smallest diff that meets every criterion; blast radius listed |
| 5 | Implement | `modern-integration`, `safe-refactor`, `root-cause-debug`, `dependency-upgrade` | Code written in the project's idiom with current APIs |
| 6 | Clean | `legacy-cleanup` | Code made obsolete by this change is removed, not left beside it |
| 7 | Test | `test-strategy` | Every criterion has a test that fails without the change |
| 8 | Verify | `verification-gate` | `verify.py` verdict PASS (or every SKIP/FAIL explained) |
| 9 | Review | `self-review` | Diff read line by line; checklist clean |
| 10 | Deliver | `git-delivery` | Committed, pushed, honest report |

## Sizing (decides depth, not whether a phase happens)

- **S** - one file, obvious location, < ~30 lines: phases 1-2 take a minute;
  run the targeted test + lint of that project only.
- **M** - several files in one module or a new feature: full pipeline, write a
  short plan in the task list.
- **L** - cross-module, schema/API change, upgrade, or unclear root cause: full
  pipeline, plan reviewed against acceptance criteria before phase 5, commit
  in reviewable steps.

## Fast start (run in parallel, one message)

```bash
python3 .claude/skills/codebase-recon/scripts/detect_stack.py   # stacks + exact commands
git status --short && git log --oneline -5                     # where am I
```
plus reading CLAUDE.md / AGENTS.md / CONTRIBUTING.md if detect_stack lists them.

## Non-negotiable rules

1. **Locate before you write.** Never edit a file you have not read in this
   session, never add a helper before searching for an existing one.
2. **Baseline before you change.** A failure you did not cause must be known
   before you start, otherwise you cannot tell whether you broke it.
3. **Replace, don't accumulate.** New code that supersedes old code removes the
   old code in the same change (callers updated, dead branches deleted).
4. **Minimal diff.** No drive-by reformatting, renames or "improvements" outside
   the task. Out-of-scope findings go in the final report, not the diff.
5. **Evidence over belief.** "Done" means a command ran and passed. Report
   SKIP/FAIL verbatim; never say "should work".
6. **Stop on surprise.** If the code contradicts the plan (behaviour differs,
   file isn't where expected, tests already red) re-enter recon instead of
   pushing forward.

## Final report template

```
What changed: <1-3 bullets, file:line links>
Why: <root cause or requirement>
Removed: <obsolete code deleted, or "none">
Verified: <commands run + verdict; tests added>
Not verified / skipped: <checks that could not run and why>
Follow-ups (out of scope): <issues noticed, not fixed>
```
