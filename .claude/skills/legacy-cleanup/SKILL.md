---
name: legacy-cleanup
description: Safely find and remove old, dead, duplicated or superseded code - unused functions/files/exports, deprecated paths, stale feature flags, commented-out code, leftover compatibility shims - proving each deletion with reference searches and passing checks. Use when asked to remove old/unused/legacy code, after replacing an implementation, when finishing a migration, or when your change makes existing code obsolete.
---

# Legacy Cleanup

Delete with proof, never with hope. Every removal is backed by (a) zero real
references and (b) green checks after deletion.

## 1. Find candidates
```bash
python3 .claude/skills/legacy-cleanup/scripts/find_dead_code.py [repo] [--path src/] [--limit 100]
```
Language-agnostic (git + regex), reports:
- symbols defined but never referenced anywhere else,
- files whose name nothing mentions (orphan modules/assets),
- `@deprecated` / legacy / "remove me" markers,
- commented-out code blocks (>= 3 lines).
It also runs a real analyzer if installed (knip/ts-prune, vulture,
deadcode/staticcheck) - prefer those results where available. For compiled
languages the compiler is the best oracle: `cargo build` dead_code warnings,
`dart analyze` unused_element, `go vet`, Kotlin/C# unused warnings.

For a change you just made, the candidates are simpler: the function/branch/
flag/file your new code replaced. Search for it by name.

## 2. Prove each candidate is dead
For every candidate, all must hold:
- [ ] `Grep -w <name>` over the whole repo (all languages, configs, templates,
      docs, CI, scripts) finds only the definition (and tests of it only).
- [ ] No string/dynamic use: `Grep "['\"]<name>['\"]"`, reflection, `getattr`,
      `import()`/`require(var)`, DI registration, routes, serializers, Android
      manifest / XML layouts, platform channels, RPC/protocol message names.
- [ ] Not public API consumed outside the repo (exported package symbol,
      library `__all__`, REST endpoint, CLI flag, firmware<->app protocol field).
      If it is: deprecate first, remove in a later release - report, don't delete.
- [ ] Not a framework hook called by name (lifecycle methods, `setup`/`loop`,
      test fixtures, signal handlers, migrations).
- [ ] `git log -S<name> --oneline | head` - understand why it exists; recent
      additions may be work in progress for someone else.

## 3. Remove completely, in one coherent change
Remove the symbol **and** everything that only existed for it: its tests,
imports, types, constants, config keys, feature flag definitions + checks
(keep the branch that is now always taken), docs mentions, assets, i18n
strings, dependencies that become unused (`npm uninstall`, remove from
pyproject, `go mod tidy`, `flutter pub remove`).
Do not leave: `// removed`, `_unused` renames, re-exports "for compatibility",
or commented-out copies. Git history is the archive.

## 4. Verify
```bash
python3 .claude/skills/verification-gate/scripts/verify.py --changed
```
plus re-run `find_dead_code.py` on the touched path: removing code often
exposes the next layer of dead code (helpers used only by what you deleted).
Iterate until stable.

## 5. Report
List what was removed and the evidence ("0 references; build + 142 tests pass").
List candidates you deliberately kept and why (public API, dynamic use,
uncertain) - never delete an uncertain candidate silently.

## Scope rule
Only remove code that the task covers or that your change made obsolete.
Large unrelated dead-code sweeps are separate commits/PRs, and only when asked.
