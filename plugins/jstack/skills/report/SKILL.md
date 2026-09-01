---
name: report
description: Close out a task — settle every finding as a commit or a filed issue, then report the result in the standard shape. Use at the end of any task that produced work.
argument-hint: "[draft]"
---

# /jstack:report — close out the task

**Fixed, or filed. Nothing real leaves in prose.** A problem mentioned only in chat dies with the session and gets rediscovered instead of fixed, so every finding exits carrying a number — a sha or `#N`.

`draft` = triage and show what would happen; file and commit nothing.

## 1. Settle every finding

A finding is a defect you confirmed. A nitpick, a taste call, an unconfirmed suspicion — not findings, and they get no commit, no issue, no report line.

**Fix-first.** If the fix is in reach in the tree you are standing in, fix it: a found break is work, not news, and filing it instead trades work for paperwork. The issue door is for what you genuinely did not fix — out of scope, another domain, needs a decision, too big for the turn. The reason goes in the body; it never changes the door.

Fix written but blocked only on a permission you lack → file it *and* hand the patch over live, since it costs something every day it waits:
`ping_boss blocker "SYSTEM FIX BLOCKED — <file>:<line> / <diff> / <cost until it lands> / #<N>"`

### Filing

Owning repo is where the problem lives, not where you stand — `git -C "$(dirname <file>)" rev-parse --show-toplevel`, then its origin. Nothing with a file behind it (a daemon, a schedule, a doc) belongs to the repo of the system that owns it; if nothing owns it, the home repo.

Check it isn't already there. A recurrence is a comment on the open issue, never a second number:
`gh issue list --repo <owner/name> --search "<distinctive words>" --state all --limit 10`

Body to a file first — prose fights shell quoting:
`file-issue --repo <owner/name> --title "<t>" --body-file <p> --label <bug|optimization|feature>`

Exactly one type label, enforced by the adapter: `bug` = broken, `optimization` = works, should be better, `feature` = doesn't exist yet. It prints `ISSUE <url> board=<col|none> type=<label|none>`; `board=none` is ordinary. A non-zero exit means nothing was filed — say that, never report a number you didn't get back.

**The body is the entire brief** for whoever picks it up, and it will be someone who was not here. The bar: they can act on it without asking a question. Plain language, short, no session jargon — what's wrong as behaviour rather than code, where, how to see it (say plainly when it was reasoned out rather than reproduced), why it matters, and the fix direction if you have one ("unknown — needs investigation" beats a guess dressed as a plan). Close with a `Found during:` line naming the task, seat, and date; that trailer is what makes it trustworthy cold.

Title: one sentence naming the symptom, understandable with no context. Not the file, not the fix.

## 2. Commit

Hand it to **`/jstack:push`**, which owns staging, splitting, and the message contract. What you owe it is the split named out loud before you push: each side fix its own unit landing *before* the main work, the deliverable one unit, generated artifacts a `chore:` unit last.

## 3. Report

Boss skims. Short, no narration, **only blocks that have content** — an empty section is noise and one invented to look thorough is worse.

- **"his question"** — one block per question he asked, answered under it
- **Blocker** — work stopped. What's needed, from whom
- **Issues** — found, not fixed. `#N — <title>`
- **Fixed** — repaired beyond the ask. `<sha> — <what>`
- **Done** — the result of the request
- **Not Done** — what wasn't, and why. Each carries `#N` or a blocker
- **Next Move** — what happens next

Read it back before sending. An **Issues** line with no `#N` means you skipped act 1; a **Fixed** line with no sha means you skipped act 2; a finding buried in another block's prose is unreferenced — it goes through a door or comes out of the report. Nothing found and nothing to commit is a normal outcome: **Done** alone, with no findings manufactured to fill sections.
