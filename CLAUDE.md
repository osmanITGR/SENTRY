# CLAUDE.md

## Repository
- Release/README home of SENTRY Tactical Control, and the marketplace for the
  project-agnostic `precision-kit` Claude Code plugin (`plugins/precision-kit/`,
  marketplace file `.claude-plugin/marketplace.json`).

## Working rules
- For every code change follow the `precision-workflow` skill (precision-kit);
  it routes to the other skills and defines the gates.
- After editing anything under `plugins/precision-kit/`, run
  `python3 plugins/precision-kit/scripts/selftest.py` and
  `claude plugin validate plugins/precision-kit` and `claude plugin validate .`.
- Skills must stay project-agnostic: no paths or names specific to one project;
  reference bundled scripts as `${CLAUDE_SKILL_DIR}/scripts/<file>`.
- Reply to the user in the language they write in (often Bangla).
