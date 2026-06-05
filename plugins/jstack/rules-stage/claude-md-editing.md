---
paths:
  - "**/CLAUDE.md"
---

# Editing CLAUDE.md

CLAUDE.md files load on every walk-up. Every line you add is paid for in context on every session that touches the cwd. Before adding content, find where it already lives.

## One canonical home per procedure

Process lives in exactly one place. CLAUDE.md sites point to it; they do not restate it. Concretely:

- Agent autonomous procedure (cron-fired, has a defined contract) → agent-scoped skill at `~/Agents/{agent}/.claude/commands/{skill}.md` (single file: description + Inputs / Outputs / Failure modes / Steps / Edge cases). Cron payload = direct `/skill_name` slash command. Sub-mode CLAUDE.md = identity + on-entry + cron schedule + hard rules only.
- Path-scoped technical pattern → `~/.claude/rules/*.md` with `paths:`. CLAUDE.md does not duplicate.
- Repeatable workflow invoked from anywhere → global slash command at `~/.claude/commands/{name}.md`.
- Project architecture → that project's own CLAUDE.md. Agent CLAUDE.md does not restate.
- Owner preference / past correction → auto-memory or feedback notes.

If the content already exists upstream, your edit is a one-line pointer — not a copy.

## Principles over examples

Write what to do and why, not the literal output shape. No verbatim report templates, no phase-by-phase walkthroughs, no agent-specific concrete examples pasted into another agent's playbook. A reader who knows the principle should be able to produce the correct shape; if they need a template, the template belongs in the canonical home, not here.

## Before editing — verify, don't assume

1. Grep for the procedure / duty / format you're about to write. If it exists elsewhere, you're pointing at it, not restating it.
2. Read the file you're editing in full. Don't add a section that contradicts or duplicates one already there.
3. If a migration changes who-does-what, check every audit signal that depends on the old contract (cron payloads, meta-review checks, tests) and update them together. A one-side edit is a contract drift.

## Bloat ceiling

Anthropic spec — each CLAUDE.md ≤ 200 lines; walk-up total (org root + agent root + sub-mode + any USER.md) ≤ 400. Going over isn't "needs trimming later" — it's a failed edit. Trim now or pick a different destination.

## Tone

Tight, conversational, declarative. No filler. No emojis. Dates as `YYYY-MM-DD`. Code/paths in backticks. Tables only when comparing ≥3 things across the same dimensions; otherwise prose is denser.
