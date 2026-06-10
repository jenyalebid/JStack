---
paths:
  - "Agents/**/state.md"
---

# Agent State Discipline — state.md

Each agent workspace carries `{agent_root}/{Name}/state.md` — the agent's live working state, the unifier across all of its sub-modes. Every session reads it on entry; the **post-session review owns all writes**.

## Who writes

- **Interactive sessions (chat, tg) NEVER write state.md.** They read it on entry, period. The review authors their state from the transcript after the session ends.
- **Autonomous modes** may leave breadcrumbs; the review reconciles.
- The post-session review is the single writer — it removes done items, adds new work, captures user corrections, and keeps timestamps honest (when things actually happened, not review time).

## Format

- Every entry dated `[YYYY-MM-DD HH:MM]`, newest at top.
- **≤50 lines AND ≤10 lines per entry.** state.md is a glanceable index, not an archive — an entry that needs more belongs in `active/{slug}.md` with a one-line pointer here. Long entries tax every session that loads the file.
- Entries >1 day stale must be resolved or removed by the review.
- Resolved work moves to a `## Recent (resolved)` section and rolls off; it does not accumulate.

## What goes here / what doesn't

- **Here:** in-flight work state, cross-mode handoffs, breadcrumbs the next session needs.
- **NOT here:** corrections or durable rules (those land in CLAUDE.md / rules / memory per the destination hierarchy), reminder shadows (the live reminder list is the source of truth), anything derivable from git history.
