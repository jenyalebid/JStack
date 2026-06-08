---
name: save
description: File the current conversation as an active item under the running agent's active/ folder.
argument-hint: "[slug] [--title \"<title>\"] [--paused] [--resume \"<trigger>\"]"
---

# /jstack:save — file the current conversation as an active item

User invoked save. They want this conversation captured so a future session can resume cold.

## Arguments

- `<slug>` — kebab-case filename. If omitted, derive from conversation topic.
- `--title "<title>"` — human title. If omitted, derive.
- `--paused` — file as `status: paused` (default is `in-progress`).
- `--resume "<trigger>"` — resume condition, required when `--paused` is set.

## Step 1 — Resolve agent root and current agent

Agent workspaces live under `${user_config.agent_root}` (set per-machine in the plugin config). The **current agent** is the `{Name}` subdirectory the working directory sits inside — the one whose `CLAUDE.md` the walk-up loaded. Active folder is `${user_config.agent_root}/{Name}/active/`.

If the working directory isn't inside any agent under `${user_config.agent_root}`, ask where to file before writing.

## Step 2 — Check active count

Count `*.md` files under `${user_config.agent_root}/{Name}/active/`. Convention: max 3 per agent. If already 3:

> Already 3 active items. Close one first, or run `/jstack:save <slug>` to overwrite a specific slug.

List the 3 with one-line "Where I am now". Wait for user decision.

## Step 3 — Derive slug + title if not provided

- **Slug** — cleanest noun phrase capturing the work. Kebab-case. 2-4 words.
- **Title** — short human phrase, sentence case.

Multiple distinct threads in conversation? Ask user which one. Don't file two from one invocation.

Thin conversation (fresh session, nothing substantial)? Ask user what to save. Don't invent context.

## Step 4 — Walk the conversation, fill the doc honestly

The doc only works if a future session can resume cold. Extract:

- **Goal** — concrete end state. One paragraph.
- **Where I am now** — single-paragraph snapshot.
- **Next moves** — 3-5 concrete near-term actions. Verb + object. Doable in one session each.
- **Progress log** — entry for this filing: `- [YYYY-MM-DD HH:MM] Filed as active via /jstack:save — <state summary>.`
- **Reference** — absolute file paths, ticket/PR numbers, session IDs, key decisions.

Get current timestamp via `date`.

## Step 5 — Write the doc

Path: `${user_config.agent_root}/{Name}/active/{slug}.md`. Format:

```markdown
---
title: <title>
slug: <slug>
status: in-progress | paused
filed: YYYY-MM-DD
last_touched: YYYY-MM-DD HH:MM
lead: <agent or owner name>
resume_trigger: <only if paused>
---

# <Title>

## Goal
<one paragraph>

## Where I am now
<one paragraph snapshot>

## Next moves
- [ ] <action>
- [ ] <action>
- [ ] <action>

## Progress log
- [YYYY-MM-DD HH:MM] Filed as active via /jstack:save — <summary>.

## Reference
- **Files:** <paths>
- **Tickets / PRs:** <numbers>
- **Conversations:** <session IDs or refs>
- **Data:** <key decisions captured>
```

If `--paused`: set `status: paused`, add `resume_trigger:` to frontmatter. Ask for resume value if `--resume` not supplied.

## Step 6 — Mirror to state.md (if it exists)

If `${user_config.agent_root}/{Name}/state.md` exists, find or create `## Active items` section near the top. Append:

```markdown
- **<title>** (`<slug>`) — <status> — <one-sentence current state>. Doc: `active/<slug>.md`.
```

If state.md doesn't exist on this agent, skip. Active doc is the canonical record.

## Step 7 — File a follow-up

Invoke the bundled adapter (it's on PATH while jstack is enabled):

```bash
file-followup "<active title>" "<one-line WHY from Goal / Where I am now>
Doc: ${user_config.agent_root}/{Name}/active/{slug}.md"
```

The adapter routes by the `followup_backend` plugin config (`none` | `todo` | `reminders` | `slack`). With the default `none` it's a silent no-op, so call it unconditionally — no existence check needed. Contract: `<title> <body>` positional args, exit 0 = filed or intentionally skipped, nonzero = failure (treat as non-fatal; the active doc is the canonical record).

## Step 8 — Confirm

One line:

> Filed as active: `{slug}`. Status {status}. {N} next moves: {a} / {b} / {c}.

The user invoked it; the confirmation is a receipt.

## What this does NOT do

- Does not promote ambient ideas to active. Active is reserved for user-directed saves.
- Does not save multiple distinct threads from one invocation.
- Does not send notifications beyond the optional follow-up adapter.

## Edge cases

- **"Save it" but unclear topic** — pick the single most important thread; ask: *"Saving as `<slug>` — that's the {summary} thread, right?"*
- **Fresh session, nothing in context** — ask what to save.
- **"Save and close X first"** — close X (delete file, remove state.md line), then file the new one.
