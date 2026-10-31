# CLAUDE.md

## Working rules
- For every code change (feature, fix, refactor, cleanup, upgrade) follow the
  `precision-workflow` skill in `.claude/skills/`; it routes to the other skills
  and defines the gates (recon -> baseline -> implement -> clean -> test -> verify -> review -> deliver).
- Find commands with `python3 .claude/skills/codebase-recon/scripts/detect_stack.py`;
  verify with `python3 .claude/skills/verification-gate/scripts/verify.py --changed`
  before every commit.
- After editing anything under `.claude/skills/`, run
  `python3 .claude/skills/precision-workflow/scripts/selftest.py`.
- Reply to the user in the language they write in (often Bangla).
