# /active — get up to speed on active items

Lists in-progress items for the running agent, or loads one for resumption.

## Arguments from $ARGUMENTS (all optional)

- (no arg) — list all active items with number, title, status, staleness, one-line "where I am now"
- `<n>` — load and brief on item number N
- `last` — alias for newest (highest-numbered)
- `oldest` — alias for active 1

Items are numbered by `filed:` date ascending — **active 1 = oldest**. Numbering is stable as long as the set is stable; when an item closes, remaining items renumber.

## Step 1 — Identify the agent

The walk-up has loaded `~/Agents/{Name}/CLAUDE.md`. That's the agent. Active folder is `~/Agents/{Name}/active/`.

If there is no agent root in the walk-up, tell the user and stop — `/active` only runs inside an agent tree.

## Step 2 — List mode (no argument)

Read every `*.md` under `~/Agents/{Name}/active/`. Sort by `filed:` ascending. For each, output one line:

```
{n}. {title}  — {status}{·N days idle if last_touched > 7d ago}  — {first line of "Where I am now"}
```

Show up to 3 items. If the count is > 3, that's a problem — the convention caps active items at 3 per agent. Flag it at the top: `⚠ {count} active — convention is max 3. Consider closing one.`

Output nothing else. The list is the answer.

## Step 3 — Load mode (numeric or alias argument)

Resolve the argument to an item:
- `1`/`2`/`3` → the n-th item by filed date
- `last` → highest n
- `oldest` → 1
- anything else: ask user to clarify, don't guess

Read the item's full markdown. Brief the user on it:

- **Title + status + filed date + last_touched**
- **Goal** verbatim
- **Where I am now** verbatim
- **Next moves** — list with checkbox state
- **Reference** — files + tickets/PRs + conversation IDs

Keep it tight. The user wants to resume, not read prose.

## Active item format

Files at `~/Agents/{Name}/active/{slug}.md`:

```markdown
---
title: <title>
slug: <slug>
status: in-progress | paused
filed: YYYY-MM-DD
last_touched: YYYY-MM-DD HH:MM
lead: <agent or owner name>
resume_trigger: <only present if status=paused>
---

# <Title>

## Goal
<one paragraph — what done looks like, concrete>

## Where I am now
<one paragraph snapshot — what's built, what's blocked, what was just discussed>

## Next moves
- [ ] <action>
- [ ] <action>
- [ ] <action>

## Progress log
- [YYYY-MM-DD HH:MM] <event>

## Reference
- **Files:** <absolute paths>
- **Tickets / PRs:** <numbers>
- **Conversations:** <session IDs or refs>
- **Data:** <key numbers / decisions captured>
```

`/save` creates these. `/active` reads them. The two skills share this format.
