# /save — file the current conversation as an active item

User invoked `/save`. They want this conversation captured so a future session can resume cold.

## Arguments from $ARGUMENTS (all optional)

- `<slug>` — kebab-case filename. If omitted, derive from conversation topic.
- `--title "<title>"` — human title. If omitted, derive.
- `--paused` — file as `status: paused` (default is `in-progress`).
- `--resume "<trigger>"` — resume condition, required when `--paused` is set.

## Step 1 — Identify the agent

The walk-up has loaded `~/Agents/{Name}/CLAUDE.md`. That's the agent root. Active folder is `~/Agents/{Name}/active/`.

If there's no agent root, ask the user where to file before writing.

## Step 2 — Check the active count

Count `*.md` files under `~/Agents/{Name}/active/`. Convention is **max 3** per agent. If already at 3:

> Already 3 active items. Close one first, or run `/save --slug X` to overwrite a specific slug.

List the 3 with one-line "Where I am now". Wait for user's decision before writing.

## Step 3 — Derive slug + title if not provided

- **Slug** — pick the cleanest noun phrase that captures the work. Kebab-case. 2-4 words.
- **Title** — short human phrase, sentence case.

If you have multiple distinct threads in the conversation, ask the user which one to save — don't file two from a single `/save`.

If the conversation is thin (fresh session, nothing substantial yet), ask the user what to save. Don't invent context.

## Step 4 — Read the conversation, fill the doc honestly

The doc only works if a future session can resume cold. Walk the conversation top to bottom and extract:

- **Goal** — concrete end state. One paragraph. If you don't know, ask one direct question before filing.
- **Where I am now** — single-paragraph snapshot. What's built/decided. What's blocked. What was just discussed.
- **Next moves** — 3-5 concrete near-term actions. Verb + object. Doable in one session each.
- **Progress log** — one entry for this filing:
  `- [YYYY-MM-DD HH:MM] Filed as active via /save — <one-sentence state summary>.`
  If earlier session events deserve preservation (commits, decisions reached upstream), add them with their actual timestamps.
- **Reference** — absolute file paths touched, ticket/PR numbers, session IDs, key data/decisions captured.

Get the current timestamp via `date` for `last_touched` and the log entry.

## Step 5 — Write the doc

Path: `~/Agents/{Name}/active/{slug}.md`. Format defined in `skills/active.md`.

If `--paused` was passed:
- Set `status: paused`.
- Add `resume_trigger: <value>` to frontmatter. If `--resume` was not supplied, ask user for the trigger before writing.

## Step 6 — Mirror into state.md (if it exists)

If `~/Agents/{Name}/state.md` exists, find or create a `## Active items` section near the top. Append:

```markdown
- **<title>** (`<slug>`) — <status> — <one-sentence current state>. Doc: `active/<slug>.md`.
```

If `state.md` doesn't exist on this agent, skip this step — the active doc is the canonical record.

## Step 7 — Confirm

One line in chat:

> Filed as active: `{slug}`. Status {status}. {N} next moves: {a} / {b} / {c}.

The user invoked the command; the confirmation is a receipt.

## What this command does NOT do

- Does not promote ambient ideas to active. Active is reserved for what the user directed via this command. Don't file unsolicited.
- Does not send notifications, file reminders, or trigger downstream automation. Pure local filing. If your machine has a reminders/notifications layer, that's a separate skill that pairs with `/save` — it's not this one.
- Does not save multiple distinct threads from one invocation. Ask user which one.

## Edge cases

- **"Save it" but no clear topic** — pick the single most important thread; ask user one sentence: *"Saving as `<slug>` — that's the {summary} thread, right?"* Wait for yes/no.
- **Fresh session with nothing in context** — ask what to save.
- **"Save and close X first"** — close X (delete file, remove state.md line if mirrored), then file the new one.
