---
name: recall
description: Use when the user asks what happened or what was done on a day or period — "/recall yesterday", "what did we do Monday?", "recall jan 24 lynda". Replays the timeline for that date and scope and outlines it for the user. Not for keyword questions ("when did we ship X?") — that's log_event grep.
argument-hint: "[yesterday|monday|jan 24|YYYY-MM-DD[..YYYY-MM-DD]] [agent[/submode]|all] [detailed]"
---

# /jstack:recall — outline what happened, from the timeline

User invoked recall. They want a readable outline of what was done — for a
date or range, for one agent or everyone. The timeline is the source; never
reconstruct a day from transcripts or your own memory of it.

## Parse the arguments

Three parts, all optional, any order:

- **When** — a date expression. Default: today. Resolve relative words with
  the `date` command, never from memory: `date +%F` for today, offsets for
  the rest (macOS `date -v-1d +%F`, GNU `date -d yesterday +%F`). A weekday
  or bare "jan 24" means the most recent past occurrence. "last week" and
  friends become a `from..to` range.
- **Who** — an agent (`lynda`), a seat (`lynda/social`), or `all`. Default:
  the agent this session belongs to (its workspace's name under the agents
  root, lowercased — spanning all its seats); not in an agent workspace →
  `all`.
- **How deep** — "detailed" / "full" / "with context" → pass `--full` so
  each entry's context blob rides along. Default: lean.

## Run it

```bash
${CLAUDE_PLUGIN_ROOT}/bin/log_event recall <YYYY-MM-DD[..YYYY-MM-DD]> [<who>] [--full]
```

(Running from a raw clone without the plugin enabled: use the `bin/` two
levels up from this skill.)

Exit 1 means nothing recorded for that scope — say so plainly and offer the
obvious widening (`all`, or a range). Don't silently retry other scopes.

## Outline it — you are summarizing for a reader, not dumping a log

- Chronological. Multiple agents → group by agent, each group still in time
  order.
- One line per event, led by what shipped / was decided / was fixed. Merge
  blocks that are one story told twice.
- Keep times coarse (morning / 14:05 — whatever serves the reader); drop
  entry ids, session ids, and anything else that smells like plumbing.
- A `↳ verdict:` on an entry is the independent review's call — surface it
  when it changes the story ("review flagged this as drift").
- `--full` context blobs are raw material for a better outline, not content
  to paste.

Depth on request: a specific entry's everything is `log_event show <id>`
(ids visible in the raw recall output); a "when did we..." follow-up is
`log_event grep`.
