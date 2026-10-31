---
name: git-delivery
description: Deliver finished work cleanly - right branch, intentional staging, conventional focused commits with clear messages, safe push with retry, and an honest final report. Use when committing, pushing, preparing a PR, splitting work into commits, or wrapping up a task.
---

# Git Delivery

## Preconditions
- `verification-gate` verdict obtained and `self-review` finished.
- On the designated branch: `git branch --show-current`. If on the default
  branch and work must not go there, create/switch to the feature branch first.
- Sync if others may have pushed: `git fetch origin <branch>` and rebase/merge
  your local commits on top (never rewrite others' history).

## Stage intentionally
```bash
git status --short
git add <explicit paths>          # not `git add -A` blindly
git diff --cached --stat          # exactly the files you mean
```
Never commit: secrets/.env, build outputs, `node_modules`, IDE files, large
binaries, local logs. Add a `.gitignore` entry if the repo lacks one for them.

## Commit
- One logical change per commit (refactor, fix, feature, cleanup separated).
  Each commit should build and pass tests on its own.
- Follow the repo's existing message style (`git log --oneline -15`); default
  to Conventional Commits:
  ```
  fix(net): reject empty scan payload with 400

  Empty bodies crashed the parser (IndexError at parser.py:41).
  Validate before parsing and add a regression test.
  ```
  Subject <= 72 chars, imperative; body explains why + notable decisions.
- Append any attribution trailers the session requires.
- Hooks fail? Fix the cause; never `--no-verify` unless the user asks.

## Push
```bash
git push -u origin <branch>
```
Retry only on network errors (backoff 2s, 4s, 8s, 16s). Non-fast-forward ->
fetch + rebase, re-verify, push again; force-push only your own branch and
only with `--force-with-lease`.
Create a PR only when asked; when you do, mirror the repo's PR template.

## Final report (to the user)
Use the template in `precision-workflow`: what changed (file:line), why, what
was removed, exact verification commands + verdict, what was not verified,
follow-ups. Same language as the user writes in.
