---
name: test-strategy
description: Design and write comprehensive tests that actually prove a change - acceptance-criteria mapping, edge/boundary/error cases, regression tests, integration and platform coverage - using the project's own test framework and layout. Use whenever code is added or changed, when asked to write/improve tests, when coverage is thin, or before claiming a feature or fix works.
---

# Test Strategy

A test is valuable only if it would fail when the code is wrong. Aim for
tests that catch real bugs, not line coverage for its own sake.

## 1. Use the house framework and layout
Find an existing test next to the code you changed and mirror it: framework
(pytest, vitest/jest, node:test, go test, cargo test, flutter_test, JUnit,
xUnit, Unity for PlatformIO), file naming, fixtures/factories, mocking style,
assertion style. Never introduce a second test framework.

## 2. Build the test matrix from the ACs
For each acceptance criterion, pick cases from every row that applies:

| Dimension | Cases |
|-----------|-------|
| Happy path | typical valid input -> expected output |
| Boundaries | 0, 1, max, max+1, empty string/list, exactly-at-limit, off-by-one |
| Invalid input | null/None/undefined, wrong type, malformed JSON/packet, negative, NaN, unicode (non-Latin scripts, emoji, RTL), very long |
| Errors | dependency throws, timeout, network down, disk full, permission denied, partial read |
| State | first call vs repeated, idempotency, ordering, concurrent calls, after reset/dispose |
| Regression | the exact input from the bug report |
| Compatibility | old data/config format still accepted; other platform path (Android/Windows, debug/release) |
| Security | injection strings, path traversal `../`, oversized payloads, auth missing/expired |

Not every row applies to every change - but decide consciously, don't skip by default.

## 3. Pick the right level
- **Unit**: pure logic, parsing, calculations, state machines - fast, many cases
  (use table-driven / parametrized tests).
- **Integration**: module boundaries, DB, HTTP handlers, serial/socket
  protocol encode<->decode round-trips - fewer, realistic.
- **End-to-end / UI**: one or two critical user flows only (widget tests,
  Playwright). Use the `run` skill to see the real app when UI changed.
Mock only what is slow, external or non-deterministic (network, clock, random,
hardware). Never mock the unit under test.

## 4. Write tests that are trustworthy
- Prove each new test can fail: break the code (or revert the fix) once and
  watch it go red. A test that cannot fail is deleted or fixed.
- Deterministic: fixed seeds, injected clock, no sleeps (await conditions),
  no reliance on test order or real network.
- Assert on behaviour/outputs, not private implementation details.
- One reason to fail per test; descriptive names: `rejects_empty_payload_with_400`.
- Hardware/firmware: extract logic from `loop()`/ISRs into pure functions and
  unit-test them natively (PlatformIO `native` env); keep hardware I/O thin.

## 5. Run
```bash
<targeted test command for the file>          # fast inner loop
<verification-gate skill dir>/scripts/verify.py --changed   # before done
```
Check coverage of the changed lines if the project has coverage tooling
(`--coverage`, `pytest --cov`, `go test -cover`) - uncovered new branches need
a test or a reason.

## Never
Skip/disable/`xfail` a test to get green; weaken an assertion to match buggy
output; update snapshots without reviewing the diff; leave `.only`/`fit`/`fdescribe`.
