# `/jstack:work` — get battle-ready on a topic

**Status:** design approved 2026-06-19 · **Author:** Jarvis (chat)

## Problem

When Boss sits down to work with an agent, he has to re-explain context every time: which app, which area, "go read the recent changes, load the SwiftUI skills first." Maggie did the right thing once by hand (session `8a047492`): loaded the SwiftUI skills, surveyed recent game-screen commits, read the core files, then gave a grounded lay-of-the-land before touching anything. `/work` makes that the one command — the agent gathers all the knowledge and loads every relevant skill to become the best it can be on that topic, with no re-explaining.

## End goal

`/work [@project] <topic>` → the agent orients, loads every skill relevant to its stack + the topic, surveys recent changes in that area, reads the core files, and reports a grounded summary — ready to execute. One sentence of "done": *the model is as prepared as a senior engineer who just finished reviewing the area, with the right tools loaded.*

## Non-goals (YAGNI)

- **No project registry, no `pipeline.json` read.** The agent already knows its own identity, project, and stack from its loaded `CLAUDE.md` walk-up. `/work` leans on that context — it does not look anything up in J&J-specific config. This keeps it a clean, portable jstack skill.
- **No state writes.** Interactive command; never touches `active.md`.
- **No code changes.** `/work` ends *ready to work*; the actual work is whatever Boss asks next.
- **No hardcoded stack→skill table.** Skill selection is by matching live skill descriptions, so new skills are picked up automatically.

## Arguments

`$ARGUMENTS` is free text. `argument-hint: "[@project] <topic>"`.

- **Project (optional).** If the first token is `@`-prefixed (e.g. `@wordy`), it's an explicit project override. Otherwise the agent uses **its own project** — the one its loaded identity already establishes (Lynda's essence is Wordy; she runs `/work review ui` and never names a project).
- **Topic (required).** Everything after the optional `@project`. Drives both which skills load and which area of code gets surveyed. Examples: `review ui`, `game screen ui changes`, `the hint flow`.

Examples:
- Lynda: `/work review ui` → Wordy (her project), Swift/iOS skills, recent Wordy UI changes.
- Mario: `/work @wordy review ui` → resolve Wordy's repo, Swift/iOS skills, recent Wordy UI changes.
- Mario: `/work review the map heat` → multi-project agent, no `@`; infer project from topic ("map heat" → MapCity). If genuinely ambiguous, ask one quick question rather than guess.

## Procedure (the spine — mirrors Maggie's session)

1. **Orient.** `date`. Read own `active.md` for cross-mode context (read-only).
2. **Resolve project → repo.**
   - `@project` given → match the name (case-insensitive) against repo directories under `${user_config.repo_root}` (default: parent of `agent_root`). No match → list candidates and stop.
   - No `@project` → use the agent's own project from its identity context. Multi-project agent with an ambiguous topic → infer from topic; if still unclear, one question.
3. **Determine stack.** The agent knows its own stack from identity. For an `@project` override, sniff the repo: `*.xcodeproj`/`Package.swift` → Swift/iOS, `package.json` → web/node, `Cargo.toml` → Rust, etc.
4. **Load the skills.** Match `stack + topic` against the live skill descriptions available this session and invoke (via the `Skill` tool) **every** skill that's relevant — not a curated minimum. `review ui` on Swift → the SwiftUI specialist / expert / what's-new skills, plus any topic-specific ones (sheets, concurrency, etc.) if the topic touches them.
5. **Survey the area.** In the repo: `git log --oneline -8`, `git status --short`, and `find`/grep for files matching the topic keywords. Review the last few commits that touched the area so the agent knows what recently changed.
6. **Read the core files.** Open the files the survey surfaced as central to the topic. Ground in what actually exists, not assumptions.
7. **Report the lay of the land.** A grounded summary: what the area is and where its code lives, what recently changed, which skills are now loaded, and the agent's read on the current state. End ready to execute — do **not** start changing code.

## Output contract

A single grounded summary message covering: project + repo resolved, stack, skills loaded, recent changes in the area, the core files read, and a short "here's the current state / I'm ready" read. No edits, no state writes, no PR.

## Genericity / placement

- Ships in `plugins/jstack/skills/work/SKILL.md`, namespaced `/jstack:work`.
- Reuses the existing `${user_config.repo_root}` / `agent_root` seam for repo resolution; adds **no** new `userConfig` keys.
- Fully portable: every project/stack fact comes from the agent's own loaded identity + repo sniffing, never from J&J config.
- Register in `plugins/jstack/systems.json` if it warrants a test; bump plugin version; update `README.md` skill list/count. Push JStack after the change (per Jarvis JStack-maintenance rule).

## Open edges (decide at implementation)

- How forcefully to cap skill loading (a topic could match many skills). Lean inclusive — Boss's intent is "become the best," so over-load rather than under-load, but skip clearly-irrelevant ones.
- Whether to also read the project's `CLAUDE.md` / nearest project doc as part of step 6 grounding (likely yes when present).
