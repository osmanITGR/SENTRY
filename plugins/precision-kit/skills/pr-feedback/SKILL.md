---
name: pr-feedback
description: Handle pull-request review comments and failing CI checks efficiently and correctly - triage every comment, fix valid ones with minimal commits, push back with evidence on incorrect ones, reproduce CI failures locally, and keep the PR mergeable. Use when a PR has review comments, requested changes, red checks, merge conflicts, or the user asks to address feedback or babysit a PR.
---

# PR Feedback

## 1. Collect everything first
Read all review comments/threads, the PR description, and every failing
check's log (first error, not last) before changing anything. Group comments
that touch the same code.

## 2. Triage each comment
| Verdict | Action |
|---------|--------|
| Valid bug/requirement | Fix + test, reply with what changed (commit SHA) |
| Valid style/nit | Fix if cheap and consistent with repo conventions |
| Unclear | Ask one precise question in the thread |
| Incorrect | Reply politely with evidence (code reference, test, docs link); don't change code |
| Out of scope | Acknowledge, propose a follow-up issue; don't expand the PR |
Never silently ignore a comment; never resolve someone else's thread without addressing it.

## 3. Fix CI failures
- Reproduce the failing command locally (same versions/flags) -> `root-cause-debug`.
- Distinguish: caused by this PR / pre-existing on base branch / flaky / infra.
  Only the first is yours to fix in this PR; report the others with evidence.
- Never skip, disable or weaken tests/checks to turn CI green.

## 4. Merge conflicts
Fetch base, rebase or merge per repo convention, resolve each conflict by
understanding both sides (not by picking "ours"), then rerun the full gate.
Force-push only your own branch, with `--force-with-lease`.

## 5. Commit and reply
- Small focused commits (`fix: handle empty payload (review)`), run
  `verification-gate` before each push.
- Reply in each thread once the fix is pushed; summarize in one PR comment if
  there were many changes. End every GitHub post with the attribution footer
  the session requires.
- Don't approve or merge on your own authority.
