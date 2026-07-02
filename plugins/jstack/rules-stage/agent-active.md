---
paths:
  - "Agents/**/active.md"
---

# Agent Active-Items Discipline — active.md

`{agent_root}/{Name}/active.md` holds **one thing: the agent's active-items index** — a one-line pointer to each open `active/{slug}.md`. Nothing else. Not a work-log, not history, not a watch-list, not pending-Boss notes. Every session reads it on entry to know what's in flight.

## The only content

```
# {Name} — state

## Active items
- **{slug}** — one-line status. → `active/{slug}.md`
```

No active items → `_None._`. That is a complete, correct active.md.

Everything that used to sprawl here now lives where it belongs:
- **What got done** → the sub-mode's `continuity.md` + the timeline.
- **Decisions / blockers / Boss-facing** → reminders (J List / J Pending) + the issue ledger.
- **The full dossier for an in-flight item** → its `active/{slug}.md`.

## Who touches it

- **The active-item lifecycle writes it.** `/save` and `/active` add a line; resolving an item removes its line (and deletes the `active/{slug}.md`). No session narrates into state.
- **The review verifies it** (for reviewed sub-modes): each review confirms every active line is still valid — item still open, status accurate, `active/{slug}.md` exists. Drift → fix the line or remove it. The review does **not** author history here.

## Hard limit

One line per active item, max 3 items per agent. If an entry needs a paragraph, that paragraph belongs in `active/{slug}.md`, not here. An active.md that grows past its active items is a bug.
