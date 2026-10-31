---
name: root-cause-debug
description: Systematically find and fix the real cause of a bug, crash, failing test, wrong output, flaky behaviour, or CI failure - reproduce, isolate, prove the cause, fix it once, and lock it with a regression test. Use for any bug report, error message, stack trace, "it doesn't work", failing CI job, or unexpected behaviour, instead of guessing at fixes.
---

# Root-Cause Debug

No fix without a reproduction; no "done" without a regression test.

## 1. Reproduce (smallest reliable trigger)
- Turn the report into a command: failing test, script, curl, CLI call.
- For CI failures: read the actual log, find the **first** error (not the
  last), reproduce that exact command locally with the same versions/env.
- Can't reproduce? Gather data (logs, versions, inputs, platform) rather than
  guessing; state clearly if the fix is unverified.

## 2. Write the failing test now
Encode the reproduction as an automated test at the lowest level that shows the
bug. It must fail for the right reason (assert message matches the symptom).

## 3. Isolate
Use the cheapest technique that narrows fastest:
- **Read the stack trace bottom-up** to the first frame in repo code.
- **Binary search**: in code (comment out half / early-return), in input (halve
  the data), in time (`git bisect run <test-cmd>` between a good and bad commit).
- **Diff a working case** against the failing one (other platform, other input,
  previous version).
- **Instrument**: targeted logs/asserts at the boundary where state goes wrong.
  Remove them afterwards.
Form one hypothesis at a time, predict what you'd observe, check it. Write
down falsified hypotheses so you don't revisit them.

## 4. Confirm the root cause
You've found it when you can explain: the trigger, the faulty line, why it
produces exactly the observed symptom, and why it didn't fail before (what
changed). If the explanation has a gap, keep going.
Ask "why" once more: is this line wrong, or is it a symptom of a wrong
contract upstream? Fix at the level where the contract is broken.

## 5. Fix once, completely
- Minimal fix at the root; no symptom patches (`try/except` around it, null
  checks that hide bad state, retry loops, sleeps for races) unless that IS
  the correct fix and you say why.
- Search for the same bug pattern elsewhere: `Grep` the faulty construct; fix
  siblings in scope or list them as follow-ups.
- Remove debug instrumentation.

## 6. Prove
- The new test fails before the fix and passes after (run both if cheap:
  `git stash` the fix, run, `git stash pop`).
- Full verification: `verify.py --changed`.
- Flaky bug: run the test repeatedly (`for i in $(seq 20); do <cmd> || break; done`).

## Anti-patterns
Changing several things at once; "fixing" by updating the expected value in a
test without proving the new value is correct; disabling/skipping the failing
test; blaming the environment without evidence.
