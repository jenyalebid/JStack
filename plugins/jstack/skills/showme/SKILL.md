---
name: showme
description: Surface the actual artifact — code, preview, image, doc, mockup, running app, web page — in its real viewer instead of describing it in text. Use when the user asks to see, show, preview, open, or look at what you've been working on.
argument-hint: "[raw|live|location] [focus]"
---

# /jstack:showme

Put the thing on screen. Not a summary of it, not the path to it. Default to acting — open it rather than asking which one, unless two candidates are equally central and the wrong pick wastes the user's time.

Arguments, both optional. The reserved token `raw` / `live` / `location` anywhere in the args is the mode; everything else is a **focus** that narrows which artifact. Focus is an explicit narrowing instruction, so do not balance it against other candidates. No focus → the most recent salient result.

## 1. Identify the artifact

Resolve the current topic's concrete result to an absolute path or URL. Locate it before opening — never open a guessed path.

The result is not always something you made. When the session ends with the ball in the user's court — a console to configure, billing to enable, an OAuth grant, a service to sign up for — the thing worth looking at is the page where they do it. Opening your code there is a miss.

## 2. Pick the surface

The mode sets where on the fidelity ladder to land:

- **`raw`** — the source behind it. The `.swift` file, not the preview. A mockup's `.html`, not the render. A doc's `.md`, not the Quick Look.
- **default** — the cheapest faithful visual. Prefer an in-code preview where the thing has or could have one: a SwiftUI `#Preview` in Xcode's canvas, a component preview, a Quick Look render. A feature that can have a `#Preview` gets it, never a full sim build. A finished static artifact just opens in its viewer.
- **`live`** — the thing actually running: sim booted and launched, dev server up, app launched, plus a screenshot. Use the project's own run / sim / device skill rather than hand-rolling the build.
- **`location`** — off the ladder. The intent is *where is this file*, so reveal it selected in the file manager instead of rendering: `open -R <abs-path>` on macOS, `nautilus --select` or the containing dir on Linux. This is the answer for a blob or binary with nothing to render. A URL has no file to reveal — say so and open it.

Open with `open-artifact <path-or-url>` (on PATH while jstack is enabled). Source on macOS goes to Xcode via `xed <file>`, falling back to `open-artifact` or `$EDITOR` elsewhere.

A setup the user must perform gets the **deepest** deep-link that lands on the exact action — that project's IAM page, the billing screen, the integration's settings tab, never the product homepage. Open every distinct page they will touch, then give a numbered checklist of what to click and what to hand back, so the loop closes.

## 3. Confirm

One line naming what opened and where. Anything you ran or previewed gets its screenshot attached, so the visual is captured rather than asserted.

## Fallbacks

Requested rung unavailable — no `#Preview`, no running server, no source — drop to the nearest rung, open that, and say which one you landed on. A nonzero exit from `open-artifact` or `xed` gets the absolute path and the failure reported so the user can open it by hand. When the topic produced nothing visual, say so and give the best textual rendering; never fabricate an artifact to open.
