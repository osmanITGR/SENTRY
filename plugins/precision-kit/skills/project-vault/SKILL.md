---
name: project-vault
description: Mandatory project knowledge vault for every code project - six files (PRD product requirements, STATE state machine, TOKENS design tokens, STACK framework versions, SCHEMA database schema, PLAN sequential plan) in docs/vault, routed from CLAUDE.md, with sections auto-detected from code and kept in sync. Use at the start of any session in a project (read PLAN first), when creating a project, before feature work (PRD), before UI work (TOKENS), before touching navigation/flows (STATE), data models (SCHEMA) or dependencies (STACK), after any change that alters what a vault file describes, and whenever a project has no vault yet.
---

# Project Vault

Six files are the project's long-term memory. `CLAUDE.md` routes each task to the one
it needs, so no session re-reads the codebase to rediscover what the product is, how
it behaves, how it looks, what it runs on, what it stores and what comes next.

```bash
V="python3 ${CLAUDE_SKILL_DIR}/scripts/vault.py"
$V status     # one line: files present, plan progress, stale or unfilled files
$V init       # create missing files + CLAUDE.md router, fill detected sections (never overwrites)
$V sync       # regenerate detected sections + router after code changes (manual text kept)
$V check      # missing / unfilled / stale / unrouted -> exit 1   (--json, --gate)
```

| # | File | Holds | Written by |
|---|------|-------|------------|
| 01 | PRD.md | problem, users, goals and non-goals, requirements FR-n with acceptance criteria, constraints | people + agent |
| 02 | STATE.md | state diagram (mermaid) and transition table | agent + **detected**: routes/screens, state enums, stores/blocs |
| 03 | TOKENS.md | token rules | **detected**: CSS variables, SCSS, Tailwind, Android colors/dimens, Flutter/Compose colors, tokens.json |
| 04 | STACK.md | technology decisions and upgrade policy | **detected**: projects, pinned runtimes, commands, direct dependencies with versions |
| 05 | SCHEMA.md | ER diagram, migration policy | **detected**: SQL CREATE TABLE, Prisma, Django, SQLAlchemy/SQLModel, @Entity (TypeORM/Room/JPA), Mongoose, EF Core, drift, Hive, GORM, migration folders |
| 06 | PLAN.md | milestone, ordered `- [ ]` steps, done, log | people + agent; progress derived from the checkboxes |

Detected content sits between `<!-- vault:auto:start/end -->` and belongs to the
tool. Everything else is yours, and `sync` never touches it.

## Mandatory rules
1. **Every code project has a vault.**
   - If `status` says MISSING, run `init` as your first action.
   - Then fill PRD and PLAN together with the user. Ask only for what you can't infer
     from the code and the README. Draft the rest yourself and mark assumptions.
2. **Session start**:
   - Read `PLAN.md`: what is next, and what is in progress.
   - Then read only the vault files the task touches (see the router table in CLAUDE.md).
3. **Before work**, by task type:

   | Task | Read first | Check |
   |---|---|---|
   | Feature or fix | PRD | the requirement it serves |
   | UI | TOKENS | use tokens, never raw values |
   | Flows | STATE | allowed transitions |
   | Data | SCHEMA | entities and migrations |
   | Dependencies | STACK | pinned versions and the upgrade policy |

4. **Same change, same commit**:
   - Code change that alters a described fact: run `sync` for the detected parts, and
     edit the manual parts (diagram, decisions, requirement status) yourself.
   - Step finished and verified: tick it in PLAN and add a log line.
5. **Commit gate**: the precision-kit pre-commit hook blocks the commit if files are
   missing, the router is absent, or detected sections are stale. Fix it with `init`
   or `sync`; never bypass it silently. `PRECISION_SKIP_VAULT=1` exists only for a user
   who explicitly declines a vault.
6. **N/A is explicit**: a file that genuinely does not apply keeps a line saying so,
   for example `Status: N/A - CLI without UI` or `Status: N/A - no persisted data`.
   Never leave it empty.

## Writing good vault content
- **PRD**:
  - Requirements are numbered (`FR-1`), and each one has testable acceptance criteria.
    `test-strategy` turns them into tests.
  - Non-goals prevent scope creep.
- **STATE**:
  - Use a mermaid `stateDiagram-v2` for the main flow (connection, mission, payment...).
  - Use a table of state → event → next state, plus the error and offline states.
- **TOKENS**:
  - Use semantic names (`color.danger`, not `red-600`).
  - Add a token before using a new value.
- **STACK**:
  - Record *why* each major choice was made.
  - Versions come from the detected section, never from memory.
- **SCHEMA**:
  - Use a mermaid `erDiagram` for relations.
  - Every migration changes this file (detected section via `sync`).
- **PLAN**:
  - Keep steps small and verifiable (`- [ ] 3. USB bridge - acceptance: works on Windows 10`).
  - Only one step is in progress at a time.
  - Add a log line with the date for each completed step.
- Keep every file short and current. The vault is for facts that save time, not prose
  (`project-memory`).
