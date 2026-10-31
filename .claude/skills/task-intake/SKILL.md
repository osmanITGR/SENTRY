---
name: task-intake
description: Turn a request (issue, chat message, vague "fix this", mixed-language prompt) into explicit acceptance criteria, scope boundaries and assumptions before any code is written. Use whenever a coding task starts, when a request is ambiguous or multi-part, when an issue/PR description must be interpreted, or when you are about to guess what the user meant.
---

# Task Intake

Wrong target = all later precision wasted. Spend one focused pass here.

## 1. Restate the task in one sentence
"Make X do Y when Z, without changing W." If you cannot write it, you do not
understand the task yet: read the linked issue/PR/comments/code first.

## 2. Extract acceptance criteria (ACs)
Write 2-7 checkable statements. Each must be verifiable by a test or command.

```
AC1  POST /scan with empty body returns 400 {error:"empty"}      (not "handle errors better")
AC2  Existing /scan happy-path response is byte-identical
AC3  No new dependency
```
Always include the implicit ones:
- existing behaviour that must NOT change (regression guard),
- the platforms/targets in play (e.g. Android + Windows build both still pass),
- performance/security constraints if the area is hot or user-facing.

## 3. Classify the request
| Type | Means | Go to |
|------|-------|-------|
| Question | Answer with evidence (file:line), change nothing | codebase-recon |
| Bug | Reproduce first | root-cause-debug |
| Feature | New behaviour + tests | modern-integration |
| Refactor | Same behaviour, better structure | safe-refactor |
| Cleanup | Remove obsolete code | legacy-cleanup |
| Upgrade | Dependency/toolchain change | dependency-upgrade |

Mixed requests: split into ordered sub-tasks in the task list; deliver each
fully (tested) before the next.

## 4. Resolve ambiguity - cheapest source first
1. The code, tests, git history (`git log -S<term>`, `git blame`) and docs.
2. Conventions already in the repo (how similar features were done).
3. A sensible default you **state explicitly** as an assumption.
4. Ask the user only when the answer changes what you build and none of the
   above settles it (e.g. destructive data migration, public API shape,
   choosing between two product behaviours). Ask once, all questions together,
   each with a recommended option.

## 5. Scope fence
Write down what is OUT of scope. Anything noticed later outside the fence goes
to "Follow-ups" in the report, never into the diff.

## Output (keep it in the task list / your head, not a document)
```
Goal: ...
ACs: AC1..ACn
Type: bug|feature|refactor|cleanup|upgrade|question
Assumptions: ...
Out of scope: ...
```
Exit gate: every AC is testable and you know which one you will verify first.
