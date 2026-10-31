---
name: modern-integration
description: Write or integrate code using current, version-correct best practices that match the project's installed versions and existing idioms - no deprecated APIs, no outdated patterns from memory, no hallucinated functions. Use when implementing features, wiring a library/SDK/API, adding endpoints/screens/components, or whenever you are about to write code against a framework or third-party package.
---

# Modern Integration

"Best current practice" = the newest correct approach **for the versions this
project actually uses**, written the way this codebase already writes things.

## 1. Pin down the real versions first
Read the lockfile/manifest, not your memory:
| Stack | Source of truth |
|-------|-----------------|
| Node | `package.json` + lockfile (`npm ls <pkg>`, `pnpm why <pkg>`) |
| Python | `pyproject.toml`/`uv.lock`/`poetry.lock`/`requirements*.txt`, `pip show <pkg>` |
| Flutter/Dart | `pubspec.yaml` + `pubspec.lock`, `flutter --version` |
| Android | `gradle/libs.versions.toml`, `build.gradle(.kts)` (AGP, compileSdk, Kotlin) |
| Go | `go.mod` (`go` directive), `go list -m all` |
| Rust | `Cargo.toml`/`Cargo.lock`, `edition` |
| .NET | `*.csproj` `TargetFramework`, `Directory.Packages.props` |
| Embedded (Arduino/ESP/STM32) | `platformio.ini` / board core version |

## 2. Verify every API you call
- Installed source beats memory: read the type definitions/docstrings in
  `node_modules/<pkg>/*.d.ts`, site-packages, `~/.pub-cache`, `$GOPATH/pkg/mod`,
  `~/.cargo/registry`. `Grep` for the exact function name there.
- Unsure an API exists in this version? Check it there or in official docs/
  changelog (WebFetch) before writing code. Never invent parameters.
- Check the deprecation notes of what you use (`@deprecated`, `DeprecationWarning`,
  `@Deprecated`, changelog "removed in").

## 3. Follow the house idiom over generic best practice
When the repo has a convention (state management, DI, error type, logger,
HTTP client, test framework, folder layout), use it - even if you'd pick
differently from scratch. Consistency beats local cleverness. Introduce a new
pattern only when the task requires it, and say so in the report.

## 4. Current-practice checklist (apply where it fits the stack)
- **Types**: full typing on new code (TS strict types, Python type hints,
  Dart null-safety, Kotlin nullability). No `any`/`dynamic`/`# type: ignore`
  without a reason in a comment.
- **Errors**: handle at the boundary that can act on them; no silent
  `catch {}`/`except: pass`; preserve cause (`raise ... from e`, `{ cause }`,
  `%w`). User-facing errors are actionable.
- **Async**: no blocking I/O on UI/event loop/main thread; cancel/timeout
  network calls; dispose subscriptions/controllers/streams.
- **Security**: validate all external input (network packets, serial data,
  query params, files); parameterised queries; no secrets in code or logs;
  least-privilege permissions (Android manifest, OAuth scopes).
- **Config**: magic numbers -> named constants or existing config; no
  hard-coded hosts/ports/paths unless the repo already centralises them there.
- **Resources**: close files/sockets/serial ports; bounded buffers/queues.
- **Platform**: keep platform-specific code behind the repo's existing
  abstraction (e.g. `Platform.isAndroid`, `#ifdef`, expect/actual).
- **Dependencies**: prefer stdlib/existing deps; adding a new one is a
  decision to report (size, maintenance, licence). Use `dependency-upgrade` for
  version changes.

## 5. Integration completeness
A feature is integrated only when every touchpoint is done:
wiring/registration (routes, DI, exports, manifest, menu), config + defaults,
migrations, docs/README/CHANGELOG if the repo keeps them, i18n strings if the
repo localises (every supported locale, including non-Latin scripts), tests, and removal of whatever
it replaces (-> `legacy-cleanup`).
