---
name: project-audit
description: Audit a whole project from every angle before calling it finished, shipping, handing over or publishing - build and tests, test coverage, security (secrets and insecure code), live dependency health, portability, code health, documentation, repo hygiene, CI, error handling, accessibility, release readiness (signing, versions, privacy policy, store requirements), licenses and the project vault - and produce one scored report (0-100 per area, grade A-F, READY / READY WITH WARNINGS / NOT READY) with a prioritised fix list. Use when the user asks whether a project is complete, production-ready, good quality, safe to release or "checked from all sides", before a release or demo, when taking over an unfamiliar project, and periodically as a health check.
---

# Project Audit

One command, every angle, an honest verdict.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/project_audit.py"                 # full audit (runs build/tests, live deps)
python3 "${CLAUDE_SKILL_DIR}/scripts/project_audit.py" --quick         # static only, minutes -> seconds
python3 "${CLAUDE_SKILL_DIR}/scripts/project_audit.py" --deep          # + clean-room portability proof
python3 "${CLAUDE_SKILL_DIR}/scripts/project_audit.py" --out AUDIT.md  # also save the report
#   --offline (skip live dependency checks)   --only security,release   --json
```

## Areas and what they reuse
| Area | Source |
|------|--------|
| Build & tests pass | `verification-gate` (`verify.py`): the project's own commands |
| Test coverage | test files vs source files, test command defined (locally or in CI) |
| Security | `secret-scan` + sensitive committed files + insecure patterns: eval, SQL by string formatting, disabled TLS verification, XSS sinks, debuggable/cleartext Android, CORS `*`, unsafe deserialisation, weak password hashing, unverified JWT |
| Dependencies | `live-modernize` (live registries/advisories): vulnerable, deprecated, majors and runtimes behind |
| Portability | `portable-project` audit (`--deep` adds the clean room) |
| Code health | `legacy-cleanup` counts, TODO debt, files over 800 lines, functions over 120 lines (`code-map` parser) |
| Documentation | README with setup/usage/dev sections (English or Bangla headings), LICENSE, CHANGELOG |
| Repo hygiene | .gitignore coverage per stack, committed caches/build outputs/binaries, files over 5 MB |
| CI/CD | CI exists, runs tests and lint, automated dependency updates |
| Error handling | swallowed exceptions, empty catch blocks, ignored promise rejections and Go errors, stray debug output |
| Accessibility | (UI only) alt text, `lang`, icon-only buttons, zoom disabled, labels, focus outline; Flutter tooltips and semantic labels |
| Release readiness | (apps and libraries) version, Android release signing, R8, launcher icon, privacy policy for mobile, code signing for desktop installers, package metadata, git tags |
| Licenses | copyleft/unknown licenses among installed direct dependencies |
| Project vault | `project-vault`: the 6 vault files exist, are filled in, are in sync, and are routed from CLAUDE.md |

## Reading the result
- **Score**: each area is 100 minus penalties (critical 35, high 15, medium 6, low 2;
  repeats of the same problem are capped). Any critical finding caps its area at 40.
- **Overall**: the weighted mean of the areas that were *checked*. It is then capped:
  any critical finding means at most 49; one high finding means at most 84; 3 or more
  high findings mean at most 74; 6 or more mean at most 64.
- **Verdict**:
  - **NOT READY**: any critical finding, any high finding in security, build, release or
    dependencies, or 5 or more high findings.
  - **READY WITH WARNINGS**: other high findings, an unverified build, or an overall
    score below 70.
  - **READY**: everything else.
- **Not checked / N/A**: an area that could not run (tool missing, `--offline`,
  `--quick`) is listed under "Not checked" and excluded from the score. An area that
  does not apply to the project type is N/A. Never present a not-checked area as
  passed.

## After the audit
1. Fix in the order of the "Fix first" list, using the skill named in each fix
   (`root-cause-debug`, `secret-scan`, `live-modernize`, `portable-project`,
   `legacy-cleanup`, `docs-sync`, `ci-setup`, `ui-verify`, `project-vault`).
2. Re-run the audit after fixing a group, and quote the before and after scores.
3. **Reviewed exceptions**: mark the line with `# audit: allow - <reason>` (the marker
   may also go on the line above). A file that defines detection rules gets
   `audit: allow-file` in its first 40 lines.
4. **Heuristics are not proof**:
   - Treat pattern findings as leads, and verify each one before changing code.
   - Treat a clean area as "no known issue found", not as "secure" or "accessible".
     For security-critical or regulated projects, recommend a human review.

## Report to the user
Give the overall score, grade and verdict; the area table; the top fixes; what was not
checked and why; and the next step. Write it in the user's language. Save the full report with
`--out` when the user wants to share it.
