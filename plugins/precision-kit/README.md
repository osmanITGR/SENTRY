# Precision Kit — সব প্রজেক্ট, সব ধরনের কাজের জন্য

Claude-এর কাজ নিখুঁত, দ্রুত আর প্রমাণসহ করার জন্য **২৮টি skill + ৩টি hook**।
কোনো নির্দিষ্ট প্রজেক্টের জন্য বানানো নয়। Node, Python, Go, Rust, Flutter/Dart,
Android/Gradle, Maven, .NET, PlatformIO/Arduino, Makefile — সব ধরনের প্রজেক্ট নিজে থেকেই চেনে, monorepo-ও।

> **English:** A project-agnostic Claude Code plugin — 28 engineering skills (mandatory project vault
> routed from CLAUDE.md, whole-project audit with scores and a release verdict, incremental code map
> for ranged reads, works-on-every-machine portability checks with a clean-room proof, live modernization against current registries/advisories, verification gate,
> secret scanning, legacy cleanup, testing, CI, docs, migrations, UI checks…) plus hooks that keep
> the code map current, inject build/test commands at session start, and block commits that leak
> secrets or fail checks. Install: `/plugin install precision-kit --marketplace osmanITGR/precision-kit`.
> Python 3.11+ (standard library only) is required for the bundled scripts.

## ইন্সটল (যেকোনো একটা)

**১. claude.ai account-এ — সব জায়গায় চলবে (web, desktop, mobile, cloud Claude Code)**
```bash
python3 scripts/package_skills.py     # dist/-এ প্রতিটা skill-এর .zip তৈরি হবে
```
তারপর claude.ai → Settings → Capabilities → Skills → প্রতিটা `.zip` আপলোড করুন।
(এই পদ্ধতিতে শুধু skill যায়, hook যায় না।)

**২. Claude Code plugin — skill + hook দুটোই (প্রস্তাবিত)**
```
/plugin install precision-kit --marketplace osmanITGR/precision-kit
```
অথবা ধাপে ধাপে: `/plugin marketplace add osmanITGR/precision-kit` → `/plugin install precision-kit@precision-kit`

**৩. শুধু নিজের কম্পিউটারে, plugin ছাড়া**
```bash
python3 scripts/install.py              # ~/.claude/skills — এই মেশিনের সব প্রজেক্ট
python3 scripts/install.py --project .  # শুধু একটা প্রজেক্ট
```
Windows-এ `python3`-এর জায়গায় `python` লিখুন।

## ২৮টি Skill

| ধরন | Skill | কাজ |
|---|---|---|
| মূল | `precision-workflow` | কাজের ধরন অনুযায়ী সঠিক skill-এ পাঠায়, প্রতিটা ধাপে gate |
| | `project-vault` | **বাধ্যতামূলক** ৬টি ফাইল (PRD, STATE, TOKENS, STACK, SCHEMA, PLAN) — CLAUDE.md থেকে রাউট করা, কোড থেকে স্বয়ংক্রিয় আপডেট |
| | `project-audit` | পুরো প্রজেক্ট ১৪টি দিক থেকে যাচাই: প্রতিটির স্কোর, গ্রেড, "রিলিজের জন্য প্রস্তুত কিনা" রায় |
| শুরু | `task-intake` | অনুরোধ থেকে যাচাইযোগ্য acceptance criteria |
| | `efficiency-guard` | সময় নষ্ট রোধ, parallel কাজ, loop-breaker |
| | `code-map` | পুরো প্রজেক্টের স্বয়ংক্রিয়-আপডেট মানচিত্র: পুরো ফাইল না পড়ে শুধু দরকারি লাইন পড়া |
| | `codebase-recon` | সঠিক file:line, আসল build/test কমান্ড |
| প্রশ্ন | `codebase-qa` | কোড সম্পর্কে প্রশ্নের প্রমাণসহ উত্তর (কোড না বদলে) |
| লেখা | `modern-integration` | ইনস্টল করা ভার্সন অনুযায়ী আধুনিক কোড, deprecated API নয় |
| | `new-project-bootstrap` | নতুন প্রজেক্ট শুরু থেকেই lint/test/CI সহ |
| | `database-migration` | ডেটা না হারিয়ে schema পরিবর্তন |
| | `dependency-upgrade` | changelog পড়ে নিরাপদ আপগ্রেড |
| | `live-modernize` | **এই মুহূর্তের** registry, নিরাপত্তা-তথ্য আর deprecation-এর সাথে চলমান কোড মিলিয়ে প্রমাণসহ ভালো হলে replace |
| উন্নতি | `safe-refactor` | আচরণ না বদলে কাঠামো পরিবর্তন |
| | `legacy-cleanup` | পুরাতন/অব্যবহৃত কোড প্রমাণসহ মোছা |
| | `performance-optimize` | মেপে মেপে গতি বাড়ানো |
| ভুল | `root-cause-debug` | reproduce → মূল কারণ → regression test |
| যাচাই | `test-strategy` | edge/error/regression — সব দিকের টেস্ট |
| | `verification-gate` | সব চেক চালিয়ে সৎ PASS/FAIL/UNVERIFIED |
| | `ui-verify` | স্ক্রিনশট নিয়ে UI যাচাই |
| | `secret-scan` | পাসওয়ার্ড/key/token commit হওয়া আটকানো |
| | `self-review` | commit-এর আগে নিজের diff রিভিউ |
| | `portable-project` | আমার কম্পিউটারে চলে এমন প্রজেক্ট অন্যের কম্পিউটার/OS/ডিভাইসেও যেন একইভাবে চলে: কারণ খোঁজা আর clean-room-এ প্রমাণ |
| ডেলিভারি | `git-delivery` | পরিচ্ছন্ন commit/push, সৎ রিপোর্ট |
| | `pr-feedback` | রিভিউ কমেন্ট ও লাল CI ঠিক করা |
| | `ci-setup` | GitHub Actions তৈরি/মেরামত |
| | `docs-sync` | ডকুমেন্টেশন কোডের সাথে মিলিয়ে রাখা |
| | `project-memory` | CLAUDE.md-তে শেখা জিনিস জমা রাখা |

## Hooks (plugin ইন্সটলে স্বয়ংক্রিয়)

- **ফাইল edit-এর পর:** code map আপডেট করে। ফাইলের গঠন বদলালে তার summary-নোট পুরাতন হয়েছে বলে মনে করিয়ে দেয়।

- **Session শুরু:**
  - repo-র stack আর আসল lint/test/build কমান্ড Claude-কে আগেই জানিয়ে দেয়।
  - code map আপডেট করে, শুধু শেষ session-এর পর বদলানো ফাইলগুলো। প্রথমবার background-এ তৈরি হয়।
  - সাথে live freshness সারাংশ দেখায় (কতগুলো নিরাপত্তা-ত্রুটি, deprecated আর পুরাতন ভার্সন)।
  - এই তথ্য দিনে একবার background-এ নতুন করে আনা হয়, তাই session শুরু ধীর হয় না।
  - বন্ধ করা যায় `freshness_on_start` অপশন দিয়ে।
- **`git commit`-এর আগে:**
  - কোড প্রজেক্টে vault না থাকলে বা কোডের সাথে না মিললে commit **আটকে দেয়** (`vault_required` অপশন)।
  - secret পাওয়া গেলে commit **আটকে দেয়**।
  - পরিবর্তিত প্রজেক্টের চেক FAIL করলে commit **আটকে দেয়**।
  - কোনো চেক চালানো না গেলে Claude-কে সেটা রিপোর্টে বলতে বাধ্য করে।
  - এই চেক বন্ধ করা যায় `verify_on_commit` অপশন দিয়ে।

## স্ক্রিপ্ট (শুধু Python 3 লাগে)

| স্ক্রিপ্ট | কাজ |
|---|---|
| `codebase-recon/scripts/detect_stack.py` | প্রজেক্ট, stack ও কমান্ড শনাক্ত |
| `verification-gate/scripts/verify.py` | সব চেক চালিয়ে রায় (exit 0/1/2) |
| `legacy-cleanup/scripts/find_dead_code.py` | অব্যবহৃত symbol/ফাইল, deprecated, comment-করা কোড |
| `secret-scan/scripts/scan_secrets.py` | secret ও sensitive ফাইল খোঁজা |
| `ci-setup/scripts/gen_ci.py` | প্রজেক্টের কমান্ড থেকে CI workflow তৈরি |
| `code-map/scripts/code_map.py` | প্রজেক্ট-মানচিত্র: `summary`, `find`, `show`, `refs`, `deps`, `note`, `stale` |
| `project-vault/scripts/vault.py` | vault তৈরি/সিঙ্ক/চেক: `init`, `sync`, `check`, `status` |
| `project-audit/scripts/project_audit.py` | পুরো প্রজেক্টের স্কোরকার্ড ও রিলিজ-রায় |
| `portable-project/scripts/portability_audit.py` | "আমার কম্পিউটারে চলে" সমস্যার কারণ খোঁজা |
| `portable-project/scripts/clean_room.py` | নতুন কপিতে global package ছাড়া ইন্সটল+টেস্ট, এই কম্পিউটারের সাথে তুলনা |
| `live-modernize/scripts/freshness_report.py` | dependency ও runtime-কে **live** registry/advisory-র সাথে তুলনা |
| `live-modernize/scripts/find_deprecations.py` | চলমান কোডে deprecated API-র file:line আর বিকল্প |

## Environment variables

| Variable | Set by | Meaning |
|---|---|---|
| `CLAUDE_PLUGIN_DATA` | Claude Code | Persistent data folder of the plugin (freshness cache); falls back to `~/.cache/precision-kit` |
| `CLAUDE_PROJECT_DIR` | Claude Code | Project root passed to hooks |
| `CLAUDE_PLUGIN_OPTION_VERIFY_ON_COMMIT` | `/plugin configure` | `false` disables running checks before `git commit` (secret scan always runs) |
| `CLAUDE_PLUGIN_OPTION_FRESHNESS_ON_START` | `/plugin configure` | `false` disables the session-start freshness line |
| `CLAUDE_PLUGIN_OPTION_VAULT_REQUIRED` | `/plugin configure` | `false` stops the commit gate from requiring the project vault |
| `PRECISION_SKIP_VAULT=1` | you, inside a commit command | only when the user explicitly declines a vault |
| `PRECISION_SKIP_VERIFY=1` | you, inside a commit command | skip checks once for proven pre-existing failures |
| `PRECISION_KIT_HTTP_FIXTURE` | tests only | JSON file that replaces live registry responses (offline selftest) |

## উন্নয়ন

এই kit-এ কিছু বদলালে চালান: `python3 scripts/selftest.py`
(২০০+ assertion, সব script ও hook আসল fixture repo-তে চালিয়ে দেখে) এবং
`claude plugin validate .`।
