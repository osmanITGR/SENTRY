---
name: ui-verify
description: Verify user-interface changes by actually rendering them - screenshots across key viewports/themes/states, before/after comparison, console-error and accessibility checks, interaction flows - instead of trusting that the code looks right. Use after any change to web pages, components, styles, layouts, mobile/desktop screens, HUDs or dashboards, and when the user reports something looks wrong.
---

# UI Verify

Compiling is not rendering. Look at it.

## 1. Launch
Use the `run` skill (or the project's dev command from `codebase-recon`) to
start the app. For web, Playwright is the default driver (Chromium is usually
available; use the project's pinned Playwright if it has one).

## 2. Capture the states that matter
For each changed screen/component:
- **Viewports**: mobile (390x844), tablet (768x1024), desktop (1440x900) - or the
  sizes the product targets.
- **Themes**: light and dark if supported; RTL / long translations if localised.
- **States**: empty, loading, error, populated, overflowing (long text, many
  items), disabled, focused/hover where relevant.
- **Before and after**: screenshot the base branch (`git stash` or a worktree)
  and the change; compare side by side. Unintended diffs elsewhere = regression.

Minimal Playwright pattern:
```js
const { chromium } = require('playwright');
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 390, height: 844 } });
const errors = []; p.on('console', m => m.type() === 'error' && errors.push(m.text()));
p.on('pageerror', e => errors.push(String(e)));
await p.goto(URL); await p.screenshot({ path: 'shot-mobile.png', fullPage: true });
```
Then open the PNGs (Read tool shows images) and inspect them.

## 3. Check beyond pixels
- Zero console errors/warnings introduced; no failed network requests.
- Interactions work: click/tap through the changed flow, keyboard navigation,
  form validation messages.
- Accessibility: labels on inputs/buttons, contrast, focus visible, alt text;
  run axe (`@axe-core/playwright`) if available.
- Native/mobile: widget/golden tests (`flutter test --update-goldens` only
  after reviewing diffs), Compose/XCTest UI tests, or emulator screenshots
  where the environment allows.

## 4. Report
Attach or reference the screenshots, list what was checked, and state what
could not be checked here (e.g. real device, Windows-only rendering).
Delete temporary screenshots/scripts from the repo unless they are intended
test assets.
