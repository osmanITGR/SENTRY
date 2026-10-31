---
name: docs-sync
description: Write and update documentation (README, setup/install guides, API docs, CHANGELOG, docstrings, comments, usage examples) so it matches the code exactly - every command, flag, path, env var and example verified by running or reading it. Use when behaviour, setup, CLI/API, config or dependencies change, when asked to write or fix docs, or when docs and code disagree.
---

# Docs Sync

Wrong docs are worse than missing docs. Every statement must be checkable.

## When code changes, check which docs it touches
`Grep` the docs (`*.md`, `docs/`, docstrings, `--help` text, OpenAPI specs,
examples/) for the names you changed: commands, flags, env vars, config keys,
endpoints, function names, file paths, version numbers. Update all hits in the
same change.

## Writing rules
- **Audience first**: user guide (install/use) vs developer guide
  (build/test/contribute) vs API reference - keep them separate.
- **Task-oriented**: numbered steps that a newcomer can follow from a clean
  machine; prerequisites with versions up front.
- **Copy-pasteable commands** in fenced blocks, one per line, no prompts
  (`$`) inside the block; platform variants (Linux/macOS/Windows) when they differ.
- **Examples that run**: minimal, realistic, with expected output.
- Match the existing tone, language(s) and structure of the project's docs; if
  docs exist in two languages, update both.
- Comments explain *why*, not *what*; delete comments the change made false.
- CHANGELOG (if kept): Keep-a-Changelog sections (Added/Changed/Fixed/Removed),
  user-facing wording, link PR/issue.

## Project vault
Vault files are documentation too: when a change alters requirements, flows, tokens,
versions, schema or plan, update the matching `docs/vault/*.md` (manual part) and run
`vault.py sync` (detected part) in the same commit (`project-vault`).

## Verify
- Run every command you document (or state explicitly which ones could not be
  run here and why).
- Check every path/link exists: `Grep`/`Glob` for files, relative links resolve.
- API docs: signatures, defaults and error codes match the code.
- Re-read as a newcomer: is any step missing (env var, service, permission)?
