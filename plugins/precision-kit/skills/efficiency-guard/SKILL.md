---
name: efficiency-guard
description: Prevent wasted time and tokens - size the task, batch independent tool calls in parallel, read only what is needed, avoid re-deriving known facts, timebox investigations, and stop loops early. Use at the start of every task, when a task starts to drag, when you notice repeated failed attempts, or before launching broad searches or subagents.
---

# Efficiency Guard

Speed comes from not doing unnecessary work, never from skipping verification.

## Before starting
- Size it (S/M/L, see `precision-workflow`) and pick the matching depth.
- Define the stop condition: which command/output means done.
- If the answer can come from a single grep or a single file, do that - no plan,
  no agent, no task list.

## Tool-call discipline
- **Parallelise**: independent reads/greps/commands go in ONE message.
  (e.g. detect_stack + git status + read CLAUDE.md together.)
- **Targeted reads**: `code-map` (`find`/`show`/`refs`) or Grep first, then Read with
  offset/limit for exactly that range.
  Read whole files only when you will edit them or must understand them fully.
- **No re-reads**: don't re-open a file you just wrote/edited to "check" it;
  the tool already confirmed it. Don't re-run a passing command without a change in between.
- **Right tool**: Grep/Glob over `find | grep` pipelines; `Edit` for exact
  changes; shell `sed` only for mechanical multi-file substitutions.
- **Inner loop first**: run the single relevant test, not the whole suite,
  while iterating; full gate once at the end.
- **Long commands**: run builds/installs in the background when you have
  other independent work; never `sleep`-poll.
- **Subagents** only for genuinely broad, independent work (large codebase
  sweeps) - they start cold and re-derive context.

## Loop breakers (stop and change approach)
- The same fix attempt failed twice -> stop editing; go back to
  `root-cause-debug` step 3 and gather evidence.
- Investigation > ~15 tool calls without narrowing -> write down what you
  know/don't know, pick the single most informative next check.
- Tool/env failure (missing SDK, no network, permissions) -> one sensible
  workaround attempt, then report it as a blocker instead of fighting it.
- Waiting on a decision only the user can make -> ask once, concisely, with a
  recommended option; continue other parts meanwhile.

## Don't
- Rebuild context the conversation already established.
- Narrate options you won't take; give one recommendation.
- Produce unrequested artifacts (extra docs, reports, refactors).
- Install heavy toolchains just to "be thorough" when a lighter proof exists -
  but do install a missing linter/test runner if it is the only way to verify.
