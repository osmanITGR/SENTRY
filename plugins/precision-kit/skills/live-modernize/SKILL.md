---
name: live-modernize
description: Continuously compare the running code with what is current in the world RIGHT NOW (live package registries, security advisories, official release feeds, toolchain deprecation warnings) and replace running code when the current version is objectively better - security fixes, deprecated/yanked packages, end-of-life runtimes, deprecated API usage, outdated versions - with tests proving nothing broke. Use when asked whether code is up to date/latest/modern, for maintenance or "update everything" requests, when a session-start freshness note reports issues, on a scheduled maintenance run, and before starting work on a long-untouched repository.
---

# Live Modernize

"Current" means **the moment this skill runs**, not the model's training data.
Every version, advisory and API recommendation must come from a live source
fetched in this run. If a source is unreachable, say "not checked" - never fill
the gap from memory.

## 1. Measure the gap (live)
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/freshness_report.py"          # dependencies + runtimes vs live sources
python3 "${CLAUDE_SKILL_DIR}/scripts/find_deprecations.py"         # deprecated APIs used by the running code
```
`freshness_report.py` reads manifests and lockfiles (npm, PyPI, Go, crates.io,
pub.dev, NuGet, Maven/Gradle). It then queries the registries and advisory
sources live (OSV, with npm/PyPI advisories as fallback) and the official
runtime release feeds (Node, Go, Rust, Flutter, Python). Results are grouped
SECURITY > DEPRECATED > RUNTIME > MAJOR > MINOR/PATCH > WAIT > UNKNOWN.
`find_deprecations.py` runs the project's own lint/build/test with deprecation
warnings switched on and lists each `file:line` with the toolchain's suggested
replacement.

If the ecosystem's own audit tool is installed, run it too:
`npm audit`, `pip-audit`, `govulncheck ./...`, `cargo audit`, `dotnet list package --vulnerable`,
`flutter pub outdated`.

## 2. Decide: is the current version actually better?
Replace only when there is **objective evidence**. Novelty alone is not a reason.

| Finding | Decision |
|---------|----------|
| Known vulnerability in the version in use | **Replace now**, to the lowest version that fixes it, or the latest compatible one; skip the cooldown |
| Deprecated / yanked / discontinued package | **Replace** with the official successor named in the deprecation notice, or the maintained alternative the ecosystem recommends |
| Runtime past end-of-life, or behind the current LTS | **Upgrade** to the current LTS/stable line the project's platform supports |
| Deprecated API usage (`find_deprecations.py`) | **Replace** with the replacement the warning or official docs name |
| Patch / minor update | **Replace** in one batch per ecosystem if all checks pass |
| Major update | Replace only after reading the official migration guide and handling every breaking change that affects this code. Otherwise report it with the guide link |
| "Newer style" with no deprecation, security or measured benefit | **Don't churn.** Mention it only if asked |
| Release younger than the cooldown (WAIT, default 7 days) | Wait, unless it is a security fix. Brand-new releases are the main supply-chain attack window |
| Pre-release (alpha/beta/rc), or a package that is unmaintained or barely adopted | Never adopt automatically |
| UNKNOWN (source unreachable) | Report as unchecked. Never assume it is fine |

## 3. Replace safely (the running code must keep running)
1. **Baseline**: run the `verification-gate` skill first and record pre-existing failures.
2. **Work on a branch.** Never update the default branch directly.
3. **One group per commit**, in priority order: security, then deprecated, then runtime, then
   deprecated APIs, then patch/minor, then majors one by one. Use the `dependency-upgrade` procedure: the
   package manager (never hand-edited lockfiles), migration guide, codemods.
4. **After each group**: run `verification-gate`, then `find_deprecations.py` again (new
   versions announce new deprecations), and `ui-verify` if UI libraries changed.
   - Green: commit, e.g. `fix(deps): bump requests 2.25.0 -> 2.32.4 (GHSA-9hjg-...)`.
   - Red and not fixable within the scope of the migration guide: revert that group
     and report it with the failing output. Keep the other groups.
5. Remove what the upgrade made obsolete (polyfills, shims, workarounds, now-unused
   deps) with `legacy-cleanup`.
6. **Deliver as a PR** for review (`git-delivery`). Merging is the user's decision.

## 4. Keep it "always"
- **Every session**: the precision-kit SessionStart hook prints a one-line
  freshness summary from cache. It refreshes the cache in the background once
  a day, so it never slows startup.
- **On a schedule**: offer the user a weekly scheduled task (fresh session per
  run) that runs this skill on the repository and opens a PR with the green
  groups. Create it only when the user agrees.
- **In CI**: `freshness_report.py` exits 1 on SECURITY or DEPRECATED, so it can
  run as a scheduled CI job (`ci-setup`).

## 5. Report
```
Checked live at <timestamp>; sources: <registries/advisory sources used; unreachable ones>
Replaced: <pkg old -> new, reason (CVE/deprecation/EOL), commit>
Deprecated APIs migrated: <file:line old -> new>
Held back: <major/WAIT/failed groups + why + migration guide link>
Not checked: <UNKNOWN items>
Verification: <commands + verdict>
```
