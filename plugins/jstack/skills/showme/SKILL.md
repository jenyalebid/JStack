---
name: showme
description: Use when the user asks to see, show, preview, open, look at, or visualize the result of what you've been working on — surfaces the actual artifact (code, preview, image, doc, mockup, running app, web page) in its real viewer instead of describing it in text. Mode token raw|live picks source-code vs live-running fidelity.
argument-hint: "[raw|live] [focus]"
---

# /jstack:showme — surface the result of the current topic, visually

User invoked showme. They don't want a text summary of what you produced — they want to **see it**, in the real viewer, right now. Your job: figure out the tangible result of the current topic, pick the right *surface* for it, and open it. Default to action — open the thing, don't ask which thing unless genuinely split.

## Arguments

`$ARGUMENTS` = `[mode] [focus]`, both optional.

- **`mode`** — a reserved token, `raw` or `live`, anywhere in the args. Omitted = **default** (preview-preferred). It sets where on the fidelity ladder to land (below).
- **`focus`** — everything that isn't the mode token. Narrows which artifact when the session touched several ("the icon", "the settings screen", "the retro doc"). It's an explicit narrowing instruction — don't try to be balanced. Omitted: show the most recent salient result; if two candidates are equally central and the wrong pick wastes Boss's time, ask one short question, otherwise take the most recent.

## The fidelity ladder — what `mode` selects

showme always picks a **surface** for the result. The mode chooses how close to raw source vs a live running environment:

- **`raw` — the code behind it.** Source file(s) in the IDE/editor, not the rendered output. iOS → the Swift file open in Xcode. Web → the source file in the editor. A generated mockup/diagram → its `.html`/`.svg`/script source, not the rendered picture. A doc → the `.md` source, not the Quick Look render. This is "show me the code version."
- **default — the cheapest faithful *visual*.** Prefer an **in-code preview** if the thing has or can have one: a SwiftUI `#Preview` in Xcode's canvas, a component/Storybook preview, a Quick Look render. Only fall to a heavier surface if no preview exists. A feature that *can* have a `#Preview` gets its preview, **not** a full sim build. A plain rendered artifact (an image, a PDF) just opens in its viewer.
- **`live` — the thing running for real.** iOS → build + boot the simulator + launch + screenshot. Web → start the dev/preview server + open the live URL. Desktop → launch the built app + screenshot. Heaviest surface, highest fidelity. Prefer the project's own run/launch skill (`run`, `sim`, `device`, or a project-specific one) over hand-rolling the build.

For a static artifact already produced (image, PDF), `default` and `live` collapse to "open it in the viewer"; `raw` shows its source if one exists, else the file itself.

## Step 1 — Identify the artifact

Reflect on this conversation. What is the concrete result of the current topic — the thing worth looking at? Resolve it to an **absolute path** (or URL, for web/live). If you produced it this session you know where it is; otherwise locate it before opening — never open a guessed path. Apply `focus` to narrow.

## Step 2 — Pick the surface (by mode), then open

`open-artifact` (bundled on PATH while jstack is enabled) hands a path or URL to the platform's default app/viewer — call it as a bare command. On macOS, code goes to Xcode via `xed <file>` (falls back to `open-artifact` / `$EDITOR` elsewhere). Do **not** just print the path or paste the code — the point of showme is the thing is now on screen.

| Result is… | `raw` (source) | default (preview / render) | `live` (running) |
|---|---|---|---|
| **iOS / mobile feature** | `xed <View>.swift` → Xcode | SwiftUI `#Preview` in Xcode's canvas if the view has / can have one; else fall to the sim | build + boot sim + launch + screenshot (use the project's run/sim/device skill) |
| **Web feature / page** | source file in editor | component/Storybook preview, or the static file in the browser | start the dev server + open the live URL |
| **Desktop app feature** | source in editor | usually same as live | launch the built app + screenshot |
| **HTML mockup / sketch** | the `.html` source in editor | rendered in the browser | rendered in the browser |
| **Image (png/jpg/svg/pdf/heic)** | its generating source if any (`.svg`, script); else the file | the image in the viewer | same as default |
| **Markdown / doc** | the `.md`/source in editor | Quick Look render (macOS `qlmanage -p`) / default app | same as default |
| **Data (csv/json)** | raw file in editor | compact table inline if clearer, else default app | same as default |
| **Code change / diff** | the changed file(s) in editor/IDE | the diff inline, or in the editor | run it, if it has a runtime surface |

**Features: preview by default, sim on `live`, code on `raw`.** "Show me the settings screen" → its SwiftUI preview in Xcode. "Show me the settings screen live" → running on the sim. "Show me the settings screen raw" → the Swift file in Xcode. Reach for the project's launch skill before hand-building.

## Step 3 — Confirm

One line: what you opened and where (`SettingsView.swift open in Xcode`, `settings-screen preview in Xcode's canvas`, `Wordy running on the sim — settings screen`, `<url> in the browser`, `Opened icon.png in Preview`). For anything you ran or previewed, attach or reference the screenshot so the visual is captured, not just asserted.

## Fallbacks

- **Nothing visual exists** (the topic produced only a decision, a config value, an explanation): say so plainly and give the best textual rendering — a tight table, the key diff, the value. Don't fabricate an artifact to open.
- **Requested surface unavailable** (no `#Preview` for a `default` request, no running server for `live`, no source for `raw`): drop to the nearest rung, open that, and say which rung you landed on and why.
- **`open-artifact` / `xed` exits nonzero** (no opener, no Xcode, bad path): report the absolute path and what failed so Boss can open it manually.
- **Ambiguous topic, no focus**: pick the most recent salient artifact and open it; mention the others in one line so Boss can `/jstack:showme <focus>` to switch.
