---
name: dependency-upgrade
description: Upgrade, add, replace or remove dependencies, SDKs and toolchains (npm/pnpm/yarn, pip/uv/poetry, Gradle/AGP/Kotlin, Flutter/pub, Go modules, Cargo, NuGet, PlatformIO/embedded cores) safely - read changelogs, migrate breaking changes, update lockfiles, remove what becomes unused, and verify. Use when bumping versions, fixing vulnerable or deprecated packages, resolving version conflicts, migrating to a new major version, or adding a new library.
---

# Dependency Upgrade

## 1. Inventory
- Current versions from the lockfile; what's outdated:
  `npm outdated` · `pnpm outdated` · `uv pip list --outdated` / `pip list -o` ·
  `flutter pub outdated` · `go list -u -m all` · `cargo outdated` (if installed) ·
  `./gradlew dependencyUpdates` (if plugin) · `dotnet list package --outdated`.
- Security: `npm audit` · `pip-audit` · `govulncheck ./...` · `cargo audit`.
- Who uses it: `Grep` imports of the package across the repo.

## 2. Plan the jump
- One package (or one tightly coupled group, e.g. React + react-dom, Kotlin +
  KSP, AGP + Gradle) per step. Never "upgrade everything" in one commit.
- Patch/minor: usually safe; still run the gate.
- Major: read the official changelog / migration guide (WebFetch) for every
  major in between. List breaking changes that touch APIs this repo uses.
- Check compatibility constraints: runtime/SDK minimums (Node, Python,
  compileSdk/minSdk, Dart SDK, Go directive), peer dependencies.

## 3. Apply with the package manager (never hand-edit lockfiles)
`npm i pkg@x` · `pnpm up pkg@x` · `uv add pkg==x` / `poetry add pkg@x` ·
`flutter pub upgrade --major-versions pkg` · `go get pkg@vX && go mod tidy` ·
`cargo update -p pkg` / edit Cargo.toml then `cargo build` · Gradle version
catalog `libs.versions.toml` · `dotnet add package pkg -v x`.

## 4. Migrate code
- Replace deprecated/removed APIs per the migration guide; use codemods when
  the project provides/recommends them.
- Compiler/analyzer warnings introduced by the upgrade are part of the job.
- Remove workarounds/polyfills/shims the new version makes unnecessary
  (`legacy-cleanup`), and dependencies that are now unused.

## 5. Verify thoroughly (upgrades break things far from the import site)
Run the `verification-gate` skill's `verify.py --include-install`.
Full run, not `--changed`. Also build the release variant if possible and run
the app (`run` skill) for UI/runtime libraries. Diff the lockfile: unexpected
transitive major bumps deserve a look.

## 6. Adding a new dependency - justify it
Only when stdlib/existing deps can't reasonably do it. Check: maintained
(recent releases), licence compatible, size/transitive weight, security
history, platform support (Android/Windows/web as needed). State the reason in
the report/commit message.
