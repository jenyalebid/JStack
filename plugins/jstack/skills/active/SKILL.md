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

After the brief, the user may give a directive to actually work on the item ("ok, let's do next move 1" / "update Where I am now to say X"). If they do, execute the work AND keep the active doc honest as you go:

- Overwrite `## Where I am now` with the new snapshot
- Append one line to `## Progress log` with the current timestamp (`date`) and a one-sentence summary of what changed
- Revise `## Next moves` — check off completed boxes, add new ones, drop obsolete
- Bump `last_touched` in frontmatter
- If `${user_config.agent_root}/{Name}/state.md` mirrors active items in `## Active items`, update the one-sentence "current state" on the matching row

This is the same touch protocol any review skill should use. Run it inline as you work — don't batch updates until end of session.

## Active item format

Files at `${user_config.agent_root}/{Name}/active/{slug}.md` use the format defined by `save`. The two skills share it.

## Edge cases

- **State.md `## Active items` count doesn't match the folder** — use the folder as source of truth for numbering; flag the mismatch in the list output. Reconcile state.md inline (add missing rows, remove orphans).
- **A file has no frontmatter or invalid frontmatter** — call it out as malformed; still number it by filename mtime fallback.
- **User invokes `/jstack:active` then immediately gives a directive in the same message** (e.g. `/jstack:active 2 — let's ship next move 1`) — brief on 2 first, then execute the directive without waiting.
