---
name: report
description: Close out a task — settle every finding as a commit or a filed issue, then report the result in the standard shape. Use at the end of any task that produced work.
argument-hint: "[draft]"
---

# /jstack:report — close out the task

The end of a task has three acts, in order. Skipping to act three is the failure this
skill exists to end.

1. **Settle every finding** — each one becomes a commit or an issue number.
2. **Commit so git tells the story** — via `/jstack:push`, which owns commit mechanics.
3. **Report** — short, in the shape below, with a reference on every claim.

`draft` as `$ARGUMENTS` = do the triage and show what act 1 and 2 *would* do, file and
commit nothing. Use it when you want the plan checked first.

---

## The one rule

> **Fixed, or filed. Nothing real leaves in prose.**

A problem you noticed and mentioned only in chat is gone the moment the session ends.
That is the whole defect being corrected here: findings were being reported and lost,
so the same break got rediscovered by the next session instead of fixed by this one.

So every real finding exits through exactly one of two doors, and both leave a number:

| Finding | Door | Report line carries |
|---|---|---|
| You fixed it | its own commit | the sha |
| You did not fix it — any reason | a GitHub issue | `#N` |

"Any reason" is literal: out of scope, another domain, needs a decision, too big for the
turn, ran out of room. The reason does not change the door. It goes in the issue body.

**Fix-first still comes first.** Filing is not a way out of work in front of you. If the
fix is in reach in the tree you are already standing in, you fix it — a found break is
work, not news. The issue door is for what you genuinely did not fix, not for what you
would rather not.

**Not everything is a finding.** A nitpick, a taste preference, a "could be nicer", a
suspicion you did not confirm — those are not defects. They get no commit, no issue, and
no report line. The gate is *is it real and did I confirm it*, not *is it big*.

---

## Act 1 — settle the findings

Walk everything this task surfaced. For each, in this order:

**1. Can I fix it here, now, in this tree?** → Fix it. It becomes its own commit (act 2).
Report it under **Fixed** with its sha.

**2. Is the fix written and blocked only by a permission I do not have?** → File the issue
*and* hand the patch over live, because a blocked fix costs something every day it waits:

```bash
ping_boss blocker "SYSTEM FIX BLOCKED — <file>:<line> / <exact diff> / <what it costs until it lands> / #<N>"
```

**3. Otherwise** → File it. This is the default for anything unfixed.

### Filing

Resolve the **owning repo** from where the problem lives, never from where you are standing:

```bash
git -C "$(dirname <the-file>)" rev-parse --show-toplevel   # repo root
git -C "<repo-root>" remote get-url origin                 # -> owner/name
```

A problem with no file behind it (a daemon's behaviour, a schedule, a doc) belongs to the
repo of the system that owns it. If nothing owns it, the home repo.

Write the body to a file first — it is prose, and prose fights shell quoting:

```bash
file-issue --repo <owner/name> --title "<title>" --body-file <path> [--label bug]
```

The adapter reads the board live from GitHub and drops the issue into the intake column
so it lands where its owner actually looks. It prints `ISSUE <url> board=<column>`. A
non-zero exit means **nothing was filed** — say so in the report, do not claim a number
you did not get.

### The title

A sentence a person understands cold, naming the symptom — not the file, not the fix.

- ✅ `Streak loss: background-abandoned dailies get deleted, day vanishes from streak`
- ❌ `Fix DailyGameManager.swift:214`
- ❌ `Bug in streak logic`

### The body — the whole point of filing

The bar: **someone who was not here can act on this without asking a question.** Boss
should be able to say "fix #32" and the session that picks it up needs nothing else.
Plain language. No session jargon. Short — an issue nobody finishes reading is an issue
nobody acts on.

```markdown
**What's wrong**
What is actually observed, in a sentence or three. Behaviour, not code.

**Where**
`path/to/file.swift:214` — or the surface/screen/daemon, if there is no single file.

**How to see it**
The steps, the command, or what surfaced it. If it was reasoned out rather than
reproduced, say that plainly: "not reproduced — found reading X, the path is unguarded."

**Why it matters**
The cost. What breaks, who notices, what it blocks. If it is small, say it is small.

**Fix direction**
What you would do, if you know. "Unknown — needs investigation" is a legitimate answer
and far better than a guess dressed as a plan.

---
Found during: <the task that surfaced this> · <agent>/<seat> · <YYYY-MM-DD>
```

That trailer is why the issue is trustworthy later: it says what the session was actually
doing when this fell out, which is the context a cold reader is missing.

### Before you file — is it already there?

```bash
gh issue list --repo <owner/name> --search "<distinctive words>" --state all --limit 10
```

A recurrence of an open issue is a **comment on it**, never a second issue. The same
break filed three times under three numbers is how a tracker becomes noise.

---

## Act 2 — commit so git tells the story

Hand the committing to **`/jstack:push`** — it owns repo resolution, staging discipline,
the message contract, and the grouping rules. Do not re-implement any of it here.

What this skill owns is the input to that grouping: **name each unit of work before you
push**, so the split is a decision and not an accident.

- Each side fix is its own unit — one commit, and it lands **before** the main work.
  Read back, the history should say *the ground was fixed, then the thing was built.*
- The task's actual deliverable is one unit.
- Generated artifacts and state files are their own `chore:` unit, last.

If a side fix is tangled in the same lines as the main change, it cannot be split, and
faking the split with a partial stage is worse than not splitting. Fold it into the main
commit and name it in the body with an `Also-fixed:` trailer.

---

## Act 3 — the report

Boss skims. Short, no narration, no padding. **Only the blocks that have content** — an
empty section is noise, and a section invented to look thorough is worse.

- **"his question, quoted or summarized"** — one block per question he asked, answer under it.
- **Blocker** — work is stopped and cannot proceed. What is needed, and from whom.
- **Issues** — found, not fixed. Every line: `#N — <title>`.
- **Fixed** — repaired along the way, beyond the ask. Every line: `<sha> — <what>`.
- **Done** — the result of the original request.
- **Not Done** — parts of the ask not completed, and why. Each carries `#N` or a blocker.
- **Next Move** — what you or he does next.

### The check that makes this real

Before sending, read your own **Issues** and **Fixed** blocks:

- A line under **Issues** with no `#N` — you skipped act 1. File it now.
- A line under **Fixed** with no sha — you skipped act 2. Commit it now.
- A finding you mentioned in the prose of another block but nowhere above — it is
  unreferenced. It goes through a door or it comes out of the report.

Nothing found and nothing to commit is a normal outcome: report **Done** alone. Do not
manufacture findings to fill sections.

---

## Failure modes (DO NOT)

- **DO NOT** file an issue for something you could have fixed in the tree you were in.
  That is trading work for paperwork, and it is the exact habit that killed the last tracker.
- **DO NOT** let a finding leave as a sentence. Fixed, or filed.
- **DO NOT** file the same break twice. Search first; a recurrence is a comment.
- **DO NOT** file an issue with a body a stranger cannot act on. A title with no context
  is a note to yourself, and you will not be the one reading it.
- **DO NOT** report a sha you did not create or an `#N` you did not get back from
  `file-issue`. If filing failed, the report says filing failed.
- **DO NOT** bury a side fix inside the main commit when it could have been its own.
- **DO NOT** pad the report with sections that have nothing in them.
