---
name: secret-scan
description: Detect passwords, API keys, tokens, private keys, credentials in URLs and sensitive files (.env, keystores, .pem) before they are committed or published, and fix them properly (env vars/secret store, rotation, .gitignore). Use before every commit or push, when adding config/credentials/connection code, when auditing a repo for leaked secrets, or whenever a value looks like a key.
---

# Secret Scan

A leaked credential is the one mistake `git revert` cannot undo.

## Run
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_secrets.py"                # added lines since HEAD + untracked files
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_secrets.py" --mode staged  # exactly what will be committed
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_secrets.py" --mode all     # audit every tracked file
```
Detects private keys, AWS/GitHub/GitLab/Slack/Google/Stripe/OpenAI/Anthropic/
npm/Twilio/SendGrid tokens, JWTs, `user:pass@` URLs, hard-coded
`password|secret|api_key|token = "..."`, credentials passed as string literals
(e.g. `connect("user", "pass")`), and sensitive files (`.env`, `*.pem`,
`*.keystore`, `id_rsa`, service-account JSON). Values are masked. Placeholders
(`changeme`, `<...>`, `${VAR}`, `os.environ[...]`) are ignored. Exit 1 = findings.
If gitleaks or trufflehog is installed, run it too for deeper coverage.

## Fix each finding
1. **Move the value out of code**: read it from an environment variable or the
   project's existing config/secret mechanism (`.env` loaded at runtime and
   gitignored, CI secrets, platform keystore, build-time injection such as
   `local.properties` / `--dart-define` / `secrets.h` in `.gitignore`).
2. **Commit a template**, not the secret: `.env.example` with empty values,
   `secrets.example.h`, and document the variable in the README.
3. **Ignore sensitive files**: add patterns to `.gitignore`; if already tracked,
   `git rm --cached <file>`.
4. **Already committed or pushed?** Removing it in a new commit is not enough:
   the secret is in history. Tell the user it must be **rotated/revoked** now;
   history rewriting (`git filter-repo`) is the user's decision, never automatic.
5. False positive after review: append `secret-scan: allow` on that line.

## Rules
- Never print a full secret in chat, logs, commit messages or PR text.
- Never "test" a found credential against the live service.
- Tests use obviously fake values (`test-token`, `AKIAEXAMPLE...`), never real ones.
