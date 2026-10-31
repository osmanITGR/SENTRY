---
name: project-memory
description: Keep a short, accurate CLAUDE.md (project memory) so future sessions start with the right commands, conventions, architecture and gotchas instead of rediscovering them. Use at the end of a task that revealed something non-obvious (a command, a trap, a convention, a decision), when a repo has no CLAUDE.md, when CLAUDE.md is stale or wrong, or when the user says "remember this".
---

# Project Memory

Every session starts cold. CLAUDE.md is the only memory that survives - keep
it small, true and useful.

## What belongs in it (only facts that save a future session real time)
- **Commands**: the exact install/dev/lint/test/build commands, especially
  non-obvious ones (env vars needed, services to start, slow test subsets).
- **Layout**: 3-8 lines mapping top-level dirs to responsibilities; where
  entry points, config and generated code live.
- **Conventions** the code doesn't make obvious: error-handling style, state
  management, naming, commit format, "always X when Y".
- **Gotchas**: things that cost time - flaky tests, platform quirks, ports,
  required tool versions, files that must be regenerated, things never to edit.
- **Decisions**: one line each for non-obvious architectural choices + why.
- **User preferences** explicitly stated (language for replies, review style).

## What does NOT belong
Anything derivable in seconds from the code or README; long prose; file-by-
file descriptions; temporary task notes; secrets; guesses.

## Procedure
1. Read the existing CLAUDE.md (and AGENTS.md if present) fully.
2. Verify each fact you add (run the command, open the file). Remove or fix
   lines you found to be wrong - stale memory is worse than none.
3. Edit in place under existing headings; keep the file under ~100 lines.
   Prefer bullets: `- Tests need Postgres: docker compose up db (port 5433)`.
4. For a new repo with no CLAUDE.md, the built-in `/init` creates a first
   draft; then trim it to the rules above.
5. Mention the update in the final report ("CLAUDE.md: added test DB note").

## Scope
Project facts go to the repo's CLAUDE.md (shared with the team, committed).
Personal preferences that apply to all projects go to `~/.claude/CLAUDE.md`
(only when the user asks).
