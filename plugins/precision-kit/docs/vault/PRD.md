# PRD - Product Requirements

> Source of truth for WHAT is built and WHY. Read before feature work; update when scope changes.

Status: Active (v2.4)

## 1. Problem
AI coding agents waste time re-reading code, guess commands and versions from memory, leave old code
behind, call work "done" without proof, and ship projects that only work on the author's machine.

## 2. Users
Developers (often working in Bangla and English) who use Claude Code on many different projects:
web, mobile (Flutter/Android), desktop (Windows installers), APIs, CLIs, embedded/Arduino.

## 3. Goals and non-goals
- Goal: one installable, project-agnostic kit that makes every task located, current, verified and portable.
- Goal: deterministic scripts (Python stdlib only) instead of prose wherever a check can be automated.
- Goal: enforcement through hooks (session start, post-edit, pre-commit), not just advice.
- Non-goal: project-specific rules (those belong in each project's CLAUDE.md and vault).
- Non-goal: replacing human security/legal review.

## 4. Requirements
| ID | Requirement | Priority | Acceptance criteria |
|----|-------------|----------|---------------------|
| FR-1 | Detect stacks and the project's own commands | Must | detect_stack.py covers Node, Python, Go, Rust, Flutter, Gradle, Maven, .NET, PlatformIO, Arduino, Make |
| FR-2 | Honest verification | Must | verify.py returns PASS/FAIL/UNVERIFIED (0/1/2); skips are reported |
| FR-3 | Safe dead-code removal | Must | find_dead_code.py finds unused symbols, orphans, markers, commented code |
| FR-4 | Live freshness against current sources | Must | registries/advisories queried at run time; unreachable sources reported as UNKNOWN |
| FR-5 | Ranged reads via an incremental code map | Must | queries ~0.1 s, only changed files re-indexed |
| FR-6 | Portability proof | Must | clean_room.py flags here=PASS/clean-room=FAIL |
| FR-7 | Whole-project audit | Must | 14 scored areas, grade, READY/NOT READY verdict |
| FR-8 | Mandatory project vault | Must | 6 files + CLAUDE.md router; commit gate blocks missing/stale vaults |
| FR-9 | Works on Windows, macOS, Linux | Must | explicit UTF-8 I/O; tests pass on Python 3.11-3.13 and an ASCII locale |
| FR-10 | Commit safety | Must | pre-commit guard blocks secrets and failing checks |

## 5. Constraints
Python 3.11+ standard library only; no network needed except live-modernize; hooks must never break a
session (fail open with a message), except the deliberate commit gates.

## 6. Open questions
- Publish to Anthropic's plugin directory once stable?

