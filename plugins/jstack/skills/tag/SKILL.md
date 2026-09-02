---
name: tag
description: File this session under a timeline subject — reuse a tag from the shared vocabulary, or mint one when nothing fits. Use when the user says /tag, "tag this", "what is this session filed under", or wants a session's subject changed.
argument-hint: "[tag] | -[tag]"
---

# /jstack:tag — file this session under a subject

A tag answers what a stretch of work was *about*, across seats and dates, and it attaches to the **session** — so every entry this session wrote, and every one it writes later, reaches the tag through its session id. The session-end self-write picks one automatically; this is the same act by hand, when the subject is already clear, the automatic pick was wrong, or the user asks what this session is filed under.

## 1. Read the vocabulary first, always

```bash
log_event tag list
```

Inside a session that answers both halves at once: the vocabulary with each tag's description and use count, and a `●` on the ones **this session already carries**. Never offer or set a tag already marked `●` — say it is already filed.

`log_event: command not found` → no timeline on this machine. Say so in one line and stop.

## 2. Branch on `$ARGUMENTS`

**Empty** — print the list, then `AskUserQuestion` with up to four candidates ranked by what this session has actually been doing, each described in its own words from the list. The tool appends "Other" itself, and that is the mint path — one question covers reuse and mint both.

**A name in the list** (exact, or normalized — case, a leading `#`):

```bash
log_event tag set <name>
```

**A name not in the list** — never mint on sight. Offer the closest two or three existing tags the same way, "Other" still meaning *mint what I typed*. Only on that branch:

```bash
log_event tag new <name> --description "one line: what work belongs under this"
log_event tag set <name>
```

Write the description as the boundary of the subject, never a restatement of the name — it is what the next session matches against. Ask the user for it if the session hasn't made it obvious.

**`-<name>` / `unset <name>`** → `log_event tag unset <name>`.

**`--session <sid>`** anywhere in the arguments retargets every write above; without it they default to this session.

Report in one line what the session is now filed under, and whether that was a reuse or a mint.

## What makes a good tag

A subject **several sessions will share**. Never the seat, never the date, never this session's headline — those are the other axes. Something that can only ever describe one sitting is not a tag. A near match beats a new tag nearly every time; the vocabulary is worth sharing only while it stays small.

Two tags on a session is a session that did two things. Four is a subject being described rather than named.

A tag on a session with no timeline entry is invisible to every read — `tail`, `show` and `grep` all reach entries through the session. Tag anyway; the entry the session ends with files itself under it.
