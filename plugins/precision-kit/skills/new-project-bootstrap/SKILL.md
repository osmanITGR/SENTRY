---
name: new-project-bootstrap
description: Start a new project, app, service, library, script or prototype the right way - current stable toolchain and framework versions, official scaffolding, lint/format/typecheck/tests/CI from the first commit, sensible structure, .gitignore, README and CLAUDE.md. Use when creating anything from scratch, adding a new package to a monorepo, or when the user says "build me a ... app/tool/site".
---

# New Project Bootstrap

The first commit decides the quality floor. Make it high and cheap.

## 0. Vault first
Run the `project-vault` skill's `vault.py init`, then write PRD.md (problem, users, FR-n with
acceptance criteria) and PLAN.md (ordered steps) with the user *before* scaffolding.
Record the chosen stack and why in STACK.md; `vault.py sync` fills the detected versions.

## 1. Choose the stack deliberately
- Use what the user specified; otherwise pick the mainstream, well-maintained
  option for the platform and state why in one line.
- **Look up current stable versions** (official docs/releases via WebFetch or
  the package manager: `npm view <pkg> version`, `pip index versions <pkg>`,
  `flutter --version`, `go version`). Never pin from memory.
- Prefer the official scaffolder: `npm create vite@latest`, `npx create-next-app@latest`,
  `uv init`, `cargo new`, `go mod init`, `flutter create`, `dotnet new`,
  `gradle init`, `pio project init`. Run non-interactively with explicit flags.

## 2. Quality tooling from commit #1
| Need | Typical choice (follow the ecosystem standard) |
|------|-----------------------------------------------|
| Format | Prettier, ruff format/black, gofmt, rustfmt, dart format |
| Lint | ESLint (flat config), ruff, go vet/golangci-lint, clippy, flutter analyze |
| Types | TypeScript `strict: true`, mypy/pyright strict-ish, null safety on |
| Tests | Vitest/Jest, pytest, go test, cargo test, flutter_test - with one real test |
| Scripts | `lint`, `typecheck`, `test`, `build`, `dev` defined in the manifest |
| CI | `ci-setup` skill, once the commands pass locally |
| Hygiene | `.gitignore` (official template for the stack), `.editorconfig`, lockfile committed |

## 3. Structure
Small, conventional layout for the framework (don't invent architecture
layers for a prototype). Config via env vars with a committed `.env.example`.
Keep secrets out from day one (`secret-scan`).

## 4. Document
- README: what it is, prerequisites, setup, run, test, build/deploy - verified.
- CLAUDE.md: commands + conventions (`project-memory`).
- License only if the user wants one.

## 5. Prove it works
Run install, lint, typecheck, test, build and the app itself once
(`verification-gate`, `run` skill). Commit: `chore: scaffold <name> with <stack>`.
