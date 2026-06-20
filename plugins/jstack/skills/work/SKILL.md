---
name: work
description: Get battle-ready on a topic before doing the work — orient, load every relevant skill, survey recent changes in the area, read the core files, and report a grounded lay of the land. Use when the user says "let's work on X", "load the skills and start on Y", or otherwise wants you prepared on an area without re-explaining context. Optional @project targets a specific app for multi-project agents.
argument-hint: "[@project] <topic>"
---

# /jstack:work — get battle-ready on a topic

User wants to start working on something and wants you fully prepared first — the same thing a senior engineer does before touching an area: load the right tools, read what recently changed, read the core files, and form a grounded read of the current state. No code changes yet. The end state is *ready to execute*, with every relevant skill loaded, so the user never has to re-explain context.

You already know who you are, what you own, and your stack from your loaded identity (the CLAUDE.md walk-up). This skill leans on that — it does **not** look anything up in a project registry.

## Arguments

`$ARGUMENTS` = `[@project] <topic>`.

- **`@project`** (optional first token, `@`-prefixed): an explicit project to target — for multi-project agents (e.g. a reviewer who spans several apps), or when the user points you at a specific app. Resolve it by matching the name case-insensitively against the repo directories under `${user_config.repo_root}` (default: the parent of `${user_config.agent_root}`). No match → list the candidates and stop; don't guess.
- **No `@project`**: use **your own project** — the one your identity already establishes. If your essence is a single app's PM, that app is the project; you never need it named. If you own multiple projects and the topic is ambiguous about which, infer the project from the topic; if it's still genuinely unclear, ask one quick question rather than guess.
- **`<topic>`** (required, everything after the optional `@project`): free text naming the area — `review ui`, `the hint flow`, `game screen ui changes`. Drives both which skills you load and which part of the code you survey.

## Procedure

Run these in order. This is the spine — don't skip steps, don't start editing code.

### 1 — Orient
`date`. Read your own `state.md` for cross-mode context (read-only — never write it from here).

### 2 — Resolve project → repo
Per the Arguments rules above. End this step knowing the exact repo directory you're working in.

### 3 — Determine the stack
You know your own stack from your identity. For an `@project` override, sniff the repo to confirm: `*.xcodeproj`/`Package.swift` → Swift/iOS, `package.json` → web/Node, `Cargo.toml` → Rust, `pyproject.toml`/`requirements.txt` → Python, etc.

### 4 — Load every relevant skill
Match `stack + topic` against the skill descriptions available this session and invoke (via the `Skill` tool) **every** skill that's relevant — load fully, not a curated minimum. The user's intent is "become the best you can be on this," so lean inclusive: load all that genuinely apply, skip only the clearly-irrelevant. Example: `review ui` on a Swift project → the SwiftUI specialist/expert/what's-new skills, plus any topic-specific ones (sheets, concurrency, design) the topic touches. Announce each as you load it.

### 5 — Survey the area
In the repo:
```bash
cd <repo> && git log --oneline -8 && echo "---" && git status --short
```
Then `find`/grep for files matching the topic keywords. Read the last few commits that touched this area (`git show` / `git log -p -- <paths>`) so you know what recently changed and why.

### 6 — Read the core files
Open the files the survey surfaced as central to the topic. If the project has a `CLAUDE.md` or a nearby design/area doc, read it too. Ground yourself in what actually exists — not assumptions.

### 7 — Report the lay of the land
Give the user one grounded summary:
- **Project + repo** resolved, and the **stack**.
- **Skills loaded** (which ones, one line each on why).
- **Recent changes** in the area — what the last few relevant commits did.
- **Core files** you read and what they are.
- **Your read** of the current state and where the topic's work would land.

End ready to execute. Do **not** change code, write `state.md`, or open a PR — `/work` is preparation. The actual work is whatever the user asks next, now that you're grounded.
