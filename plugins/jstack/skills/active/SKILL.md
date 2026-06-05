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

## Step 1 — Identify the agent

The walk-up has loaded `~/Agents/{Name}/CLAUDE.md`. That's the agent. Active folder is `~/Agents/{Name}/active/`.

If there's no agent root in the walk-up, tell the user and stop — `/jstack:active` only runs inside an agent tree.

## Step 2 — List mode (no argument)

Read every `*.md` under `~/Agents/{Name}/active/`. Sort by `filed:` ascending. For each, output one line:

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

## Active item format

Files at `~/Agents/{Name}/active/{slug}.md` use the format defined by `save`. The two skills share it.
