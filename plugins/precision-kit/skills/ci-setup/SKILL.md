---
name: ci-setup
description: Create or repair continuous integration (GitHub Actions, adaptable to GitLab CI) that runs the project's own install/lint/typecheck/build/test on every push and PR, with correct toolchain versions, caching, monorepo jobs and least-privilege permissions; also release workflows. Use when a repo has no CI, CI is red or slow, a new project/stack was added, or the user asks for automation, pipelines, workflows or auto-release.
---

# CI Setup

CI must run exactly what developers run locally - no second, drifting definition.

## 1. Generate from the repo's own commands
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/gen_ci.py"            # print workflow YAML
python3 "${CLAUDE_SKILL_DIR}/scripts/gen_ci.py" --write    # write .github/workflows/ci.yml
```
One job per detected project with toolchain setup (version from `.nvmrc`,
`.python-version`, `go.mod`, `global.json` when present), dependency cache,
`working-directory` for monorepos, `permissions: contents: read`,
`concurrency` cancel-in-progress and a timeout. Projects that need manual
setup (e.g. embedded boards needing an FQBN) are listed as comments.
An existing workflow is never overwritten without `--force`: merge by hand.

## 2. Review before committing
- **Action versions**: the generator pins known majors. Check each action's
  releases page and bump to the current major (`modern-integration` rule:
  verify, don't assume).
- **Versions match local**: language version = what the project declares; add a
  matrix (e.g. OS: ubuntu/windows/macos, or several runtime versions) only when
  the project supports them.
- **Secrets** via `${{ secrets.NAME }}` only; never echo them; `pull_request`
  from forks has no secrets - don't design jobs that need them there.
- **Pin third-party actions** to a commit SHA in security-sensitive repos.
- **Fast feedback**: lint/typecheck before slow builds; cache dependencies;
  path filters (`on.push.paths`) for big monorepos.

## 3. Release workflows (when asked)
Trigger on tags (`on: push: tags: ['v*']`), build artifacts per platform
(matrix), attach them to a GitHub Release, publish checksums (SHA-256) beside
them, use `permissions: contents: write` only in that job. Signing keys come
from secrets, decoded into temp files at run time and never committed.

## 4. Verify
- Validate syntax: `python3 -c "import yaml,sys;yaml.safe_load(open(sys.argv[1]))" .github/workflows/ci.yml`
  (or `actionlint` if installed).
- Every `run:` command must already pass locally (`verification-gate`).
- After pushing, check the run result (GitHub MCP/`gh run list`) and fix red
  jobs with `root-cause-debug` - never by deleting steps.
