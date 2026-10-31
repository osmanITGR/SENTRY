---
name: self-review
description: Review your own diff line by line like a strict senior reviewer before committing - correctness, scope creep, leftovers, security, consistency, missing pieces. Use after implementation and verification and before every commit or PR, and whenever the user asks you to double-check, review, or make sure the work is correct.
---

# Self-Review

Read the diff as if someone else wrote it and you must approve it.

## 1. Get the full picture
```bash
git status --short
git diff --stat HEAD
git diff HEAD            # read ALL of it, including untracked files (git add -N . first)
```
Every file in `--stat` must be one you meant to change. Unexpected file ->
revert it or explain it.

## 2. Checklist (go through every item; most bugs hide in the ones skipped)

**Correctness**
- [ ] Each acceptance criterion is implemented and has a test.
- [ ] Edge cases: empty/null, zero, max, error paths, concurrent use.
- [ ] Every new branch/condition is reachable and correct (watch inverted
      conditions, `<` vs `<=`, wrong variable from copy-paste).
- [ ] Errors are handled or propagated, never swallowed.
- [ ] All call sites updated for any signature/behaviour change.

**Scope & cleanliness**
- [ ] No unrelated changes (formatting, renames, refactors outside the task).
- [ ] No leftovers: debug prints/logs, `console.log`, `print(`, `TODO` you
      introduced, commented-out code, `.only`/`skip`, temp files, hard-coded
      test values, local paths.
- [ ] Code made obsolete by this change is deleted (`legacy-cleanup`).
- [ ] No duplicated logic that an existing helper already provides.

**Consistency**
- [ ] Naming, error handling, logging, file placement match neighbouring code.
- [ ] Types precise (no new `any`/`dynamic`/ignores without reason).
- [ ] Public API/docs/README/CHANGELOG/i18n updated if behaviour visible to users changed.

**Safety**
- [ ] No secrets, tokens, keys, personal data in code, tests, logs or commits.
- [ ] External input validated; no injection, path traversal, unsafe deserialisation.
- [ ] Resources closed; no new blocking call on UI/main thread/event loop.
- [ ] Migrations/data changes are reversible or the risk is stated.

## 3. Optional deeper pass
For M/L changes run the built-in `/code-review` (or the `security-review`
skill for auth/input/crypto changes) and address real findings.

## 4. Fix, then re-verify
Any change made during review -> rerun the relevant checks
(`verify.py --changed`). Review is finished only when a re-read of the diff
produces no new findings.
