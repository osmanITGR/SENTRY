---
name: portable-project
description: Make sure a project that works on this machine works the same on anyone else's computer, OS or device - finds "works on my machine" causes (globally installed packages/CLIs, unpinned runtimes, missing/out-of-sync lockfiles, files that exist only locally, absolute paths, case-sensitivity, CRLF, missing exec bits, undocumented env vars, platform encoding) and proves the fix with a clean-room install and test from a fresh clone. Use before sharing/handing over/deploying a project, when someone says it fails on their machine, when onboarding a teammate, after adding dependencies or config, and when setting up a new project or CI.
---

# Portable Project

"Works on my machine" is a claim about the machine. The goal: a stranger
clones the repo, follows the README, and gets the same result.

## 1. Find the causes (static, seconds)
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/portability_audit.py"            # HIGH / MEDIUM / LOW findings with a fix each
```
| Kind | What breaks elsewhere |
|------|----------------------|
| `undeclared` | imports or script binaries (`tsc`, `eslint`, `yaml`...) that only work because they are installed globally or transitively |
| `lockfile` | missing, uncommitted or out-of-sync lockfile, so others resolve different versions |
| `toolchain` | Node/Python/Flutter/.NET/JDK/Gradle/PlatformIO versions not pinned |
| `local-only` | files the code reads that exist here but are not in git (ignored or untracked) |
| `abs-path` | `/home/me/...` or `C:\Users\me\...` in code |
| `case` | `./utils/format` vs `Format.js`: works on Windows/macOS, fails on Linux/CI |
| `line-endings`, `exec-bit` | CRLF shell scripts, `permission denied` on `gradlew`/`*.sh` |
| `env` | environment variables used in code but documented nowhere |
| `encoding` | Python text I/O without `encoding=` (Windows uses a legacy code page) |

## 2. Prove it (clean room, minutes)
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/clean_room.py" --compare                   # committed state vs this machine
python3 "${CLAUDE_SKILL_DIR}/scripts/clean_room.py" --include-uncommitted       # what the next commit will contain
```
The clean room works like this:
1. Clones only what is committed.
2. Strips global npm/pnpm/yarn/pip-user binaries from PATH, so only the language runtimes stay.
3. Disables user site-packages and creates a fresh venv per Python project.
4. Uses empty package caches.
5. Installs from the lockfile (`npm ci`, `uv sync`...), then runs lint/build/test with the
   project's own commands.

With `--compare`, it also runs the same checks here and flags every
**`here=PASS clean-room=FAIL` as a PORTABILITY BUG**. That is the exact list of
"works on my machine" problems.

## 3. Fix in this order
1. **Undeclared dependencies**: add them to the manifest as dev/runtime deps
   (`npm add -D typescript`, `uv add pyyaml`). Never document "install X globally".
2. **Lockfiles**: generate, commit, and install with the frozen command (`npm ci`,
   `pnpm install --frozen-lockfile`, `uv sync --locked`, `poetry install --sync`).
3. **Pin toolchains** in files that tools read automatically:
   - Node: `.nvmrc` + `"engines"` + `"packageManager"` (Corepack)
   - Python: `.python-version` + `requires-python`
   - Go: the `go`/`toolchain` lines in `go.mod`
   - Rust: `rust-toolchain.toml`
   - .NET: `global.json`
   - Flutter: `.fvmrc` or `environment: flutter:`
   - JVM: Gradle wrapper + `jvmToolchain`
   - PlatformIO: `platform = x@ver` and `lib_deps` with versions
   - Arduino: a `sketch.yaml` profile
   - Polyglot projects: `.tool-versions` (mise/asdf)
4. **Local-only files**:
   - Real assets: commit them.
   - Secrets or machine config: commit an example (`config.example.json`, `.env.example`).
     Load the real file with a clear error that says how to create it.
5. **Paths**:
   - Build paths relative to the project (`Path(__file__).parent`, `import.meta.url`, `path.join(__dirname, ...)`).
   - Use OS app-data APIs for user data.
   - Never concatenate with `\` or `/` by hand.
6. **Case, line endings, exec bits**:
   - Fix the import case.
   - Add a `.gitattributes` with these lines:
     `* text=auto`, `*.sh text eol=lf`, `gradlew text eol=lf`, `*.bat text eol=crlf`.
   - Mark scripts executable: `git update-index --chmod=+x <script>`.
7. **Env vars**: list every variable in `.env.example` with a comment. Validate
   required ones at startup with a message naming the missing variable.
8. **Encoding / locale / time zone**: use `encoding="utf-8"` and explicit time zones (UTC
   internally). Don't depend on the system locale for parsing numbers or dates.

## 4. Lock it in so it stays portable
- **One-command setup**: the README's setup section must work from a fresh clone. Verify it
  with `clean_room.py` (`docs-sync`). Optionally add a `setup` script: `make setup`,
  `npm run setup`, `scripts/setup.ps1` + `setup.sh`.
- **Cross-OS CI**: run the project's checks on every OS your users have:
  `gen_ci.py --os ubuntu-latest,windows-latest,macos-latest` (`ci-setup`).
- **Containers (optional, for services)**:
  - A `.devcontainer/devcontainer.json` or `Dockerfile` with the pinned runtime.
  - Base images pinned by version, not `latest`.
- **Mobile/desktop apps**:
  - Test the release build on a clean emulator/VM or a second device, not only the dev machine.
  - Check minimum OS/SDK versions (`minSdk`, Windows 10 vs 11, macOS version).
  - Check required runtimes (VC++ redistributable, WebView2), permissions, and the first-run
    experience with no existing app data.
- **Hardware/embedded**: pin the board core and library versions, and document the drivers
  (USB-serial) and permissions (`dialout` group on Linux) a new computer needs.

## 5. Report
```
Audit: <n> HIGH / <n> MEDIUM fixed (list), remaining (why)
Clean room: <verdict>; portability bugs found -> fixed: <list>
Pinned: <runtime versions + files>
Not verifiable here: <other OS / device / hardware> -> covered by <CI matrix / manual step>
```
