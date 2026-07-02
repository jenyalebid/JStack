---
name: active
description: List or load active items for the running agent.
argument-hint: "[n | last | oldest]"
---

# /jstack:active — get up to speed on active items

Lists in-progress items for the running agent, or loads one for resumption.

## Arguments

- (no arg) — list all active items with number, title, status, staleness, one-line "where I am now"
- `<n>` — load and brief on item number N
- `last` — newest (highest-numbered)
- `oldest` — active 1

Items numbered by `filed:` date ascending — **active 1 = oldest**. Numbering is stable as long as the set is stable.

## Step 1 — Resolve agent root and current agent

Agent workspaces live under `${user_config.agent_root}` (set per-machine in the plugin config). The **current agent** is the `{Name}` subdirectory of that root the working directory sits inside — the one whose `CLAUDE.md` the walk-up loaded. Its active folder is `${user_config.agent_root}/{Name}/active/`.

If the working directory isn't inside any agent under `${user_config.agent_root}`, tell the user and stop — `/jstack:active` only runs inside an agent tree.

## Step 2 — List mode (no argument)

Read every `*.md` under `${user_config.agent_root}/{Name}/active/`. Sort by `filed:` ascending. For each, output one line:

```
{n}. {title}  — {status}{·N days idle if last_touched > 7d ago}  — {first line of "Where I am now"}
```

Show up to 3 items. If count > 3, flag at top: `⚠ {count} active — convention is max 3.` Convention can be tightened by the agent's CLAUDE.md.

Output nothing else. The list is the answer.

## Step 3 — Load mode (numeric or alias argument)

Resolve argument to an item:
- `1`/`2`/`3` → n-th item by filed date
- `last` → highest n
- `oldest` → 1
- else: ask user to clarify

Read the item's full markdown. Brief the user:

- **Title + status + filed date + last_touched**
- **Goal** verbatim
- **Where I am now** verbatim
- **Next moves** — list with checkbox state
- **Reference** — files + tickets/PRs + conversation IDs

Keep it tight.

## Step 4 — Post-brief work tracking

After the brief, the user may give a directive to actually work on the item. Do the work. **Do not touch the active doc to record progress as you go** — post-session-review reads the session JSONL and writes one consolidated update (new `Where I am now`, new progress-log line, revised next moves, fresh `last_touched`) when the session ends. Mid-session edits duplicate that work and waste tokens.

Touch the active doc mid-session only when:

- The user explicitly directs an edit ("update Where I am now to say X", "check off next move 2")
- A state change must be visible to a *concurrent* session right now — rare
- A `active.md` `## Active items` row contradicts current truth in a way that will mislead a parallel reader before session end

Otherwise the live model focuses on the work; the reviewer does the bookkeeping.

## Active item format

Files at `${user_config.agent_root}/{Name}/active/{slug}.md` use the format defined by `save`. The two skills share it.

## Edge cases

- **active.md `## Active items` count doesn't match the folder** — use the folder as source of truth for numbering; flag the mismatch in the list output. Reconcile active.md inline (add missing rows, remove orphans).
- **A file has no frontmatter or invalid frontmatter** — call it out as malformed; still number it by filename mtime fallback.
- **User invokes `/jstack:active` then immediately gives a directive in the same message** (e.g. `/jstack:active 2 — let's ship next move 1`) — brief on 2 first, then execute the directive without waiting.
