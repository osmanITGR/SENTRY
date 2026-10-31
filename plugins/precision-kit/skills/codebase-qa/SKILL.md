---
name: codebase-qa
description: Answer questions about a codebase - how something works, where it is, why it behaves a certain way, what would break, how to use an API - with verified evidence (file:line, command output) and no guessing or code changes. Use for "how does X work", "where is Y", "why does Z happen", "explain this code", "what does this function do", architecture overviews, onboarding questions, and impact analysis.
---

# Codebase Q&A

An answer is only as good as its evidence. Read, run, then explain.

## 1. Pin the question
Rephrase it to something checkable: "Which code path handles a dropped
connection, and what does the user see?" If it has several parts, answer each.

## 2. Gather evidence (parallel, targeted)
- `Grep` literal strings (UI text, error messages, routes, config keys) and
  symbol definitions; follow the call chain from entry point to the behaviour.
- Read the relevant functions fully, plus their tests (tests show intended behaviour).
- `git log -S'<term>' --oneline` / `git blame -L` for "why is it like this".
- When static reading is ambiguous, **run it**: a quick script, REPL, test, or
  the app with logging - observed behaviour beats inference.

## 3. Answer
- Lead with the direct answer in 1-3 sentences.
- Then the evidence: `path/file.ext:line` references for each claim, short
  quoted snippets only where they clarify.
- Describe the flow as numbered steps for "how does X work" questions; a small
  diagram (ASCII/mermaid) only when it genuinely helps.
- Mark confidence honestly: verified (ran it / read it) vs inferred. Say what
  you could not determine and how to find out.
- Impact questions ("what breaks if...") list every call site/consumer found
  and the risk for each.

## Rules
- Do not modify code while answering unless asked; offer the fix separately.
- No invented APIs, files or behaviour - if it isn't in the code or output, it
  isn't in the answer.
- Match the user's language and technical level.
