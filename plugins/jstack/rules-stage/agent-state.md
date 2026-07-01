---
paths:
  - "Agents/**/state.md"
---

# Agent State Discipline — state.md

`{agent_root}/{Name}/state.md` is the agent's cross-mode snapshot of **what is open right now** — the unifier every sub-mode reads on entry. It is NOT a history log. What got done lives in each reviewed sub-mode's `continuity.md` and in the timeline. state.md never accumulates resolved-work prose.

## What's in it — and nothing else

- **Active items** — one line each: `**slug** — one-line status → active/{slug}.md`. The detail lives in the `active/*.md`; never inline it here.
- **Open cross-mode handoffs** — a breadcrumb the next sub-mode genuinely needs to pick up in-flight work.
- **Pending Boss** — live items that also have a reminder counterpart (no shadows).

**No `## Recent (resolved)` section.** When work resolves, its line is **removed**, not moved to an archive. The record is in git, the timeline, and continuity — not here.

## Who writes

- **Reviewed sub-modes** (the post-session review fires for them — `review.json` `reviewed_submodes`: `*/chat` plus the agent's recurring autonomous modes): the **review** authors state.md from the transcript. Interactive chat never self-writes.
- **Un-reviewed autonomous modes** (no review fires): **self-maintain** — update your own state.md line at end of run if in-flight state changed. No review will do it for you.
- Timestamps are when things actually happened, not write time.

## Hard limits

- **≤ 30 lines total.** It's a glanceable index. Over the floor = you're logging history that belongs in continuity/timeline — cut it.
- Every active item is a one-line pointer. An entry that needs a paragraph belongs in `active/{slug}.md`.
- Stale in-flight state (work shipped or dropped) gets removed, not left to rot.

## Never here

Corrections or durable rules (→ CLAUDE.md / rules / memory), reminder shadows (the live list is truth), resolved-work narration (→ continuity + timeline), anything derivable from git.
