---
name: issue
description: Work a GitHub issue end to end — read it, put it on the work board, build the fix in a worktree, open the PR, answer on the issue. Runs when an issue is assigned to the agent account.
argument-hint: "<owner/repo#N>"
---

# /jstack:issue — work one GitHub issue

You were spawned by an assignment. Someone put `owner/repo#N` on the agent account, and
this session exists to take that issue from open to a PR waiting to be merged.

The issue body is your whole brief. Nobody is standing by to explain it — read it, decide,
build, and answer **on the issue**, because the issue is the only place your answer
survives. This session's prose does not.

## Arguments

`$ARGUMENTS` = `owner/repo#N`. No argument means you were opened by hand: ask which issue,
do not guess.

## The two contracts

Break either and the machinery around this skill stops working.

1. **The branch is `issue-<N>`.** Exactly that. When the issue is closed, a merge is
   attempted against the open PR whose head is `issue-<N>` — there is no other record of
   which branch belonged to which issue. A branch named anything else is work that never
   merges.
2. **You do not switch branches in a shared checkout.** Every agent on this machine shares
   one working tree per repo. `git checkout -b` there moves the branch under everyone
   else's feet mid-edit. Use a worktree (step 3); there is no exception for "just a small
   change."

## Procedure

### 1 — Read the issue, all of it

```bash
gh issue view <N> --repo <owner/repo> --json title,body,labels,state,url,comments
```

Comments included: a re-assignment or a resume means there may be a conversation above you
already. The **last** comment is usually the most recent instruction.

The type label tells you what is being asked: `bug` = something is broken, restore the
claimed behaviour. `optimization` = it works, make it faster/cheaper/simpler/clearer
without changing what it does. `feature` = it does not exist, build it.

If the body genuinely cannot be acted on — it names no symptom, no surface, no ask — do
not guess at a fix. Go to **Blocked** below.

### 2 — Put it on the board

```bash
place-issue --repo <owner/repo> --issue <N> --status "In Progress"
```

Defaults to the **Auto-Work** board. `place-issue --repo <owner/repo> --list-boards` shows
every board and its columns if the work clearly belongs on another one — pick by fit, and
say in your issue comment which board you chose and why. Adding is idempotent, so a
resumed session re-running this does not duplicate its card.

A non-zero exit means the card is not where you say it is. Report that in your comment
rather than claiming a column you did not get.

### 3 — Get a worktree

Find the repo's checkout on this machine, then branch **beside** it, never inside it:

```bash
WT=<your-seat>/pad/issue-<N>
git -C <repo-root> worktree add "$WT" -b issue-<N>     # first time
git -C <repo-root> worktree add "$WT" issue-<N>        # branch already exists (resume)
cd "$WT"
```

Already there from an earlier turn? Use it as is. Everything from here happens in `$WT`.

If the repo is not checked out on this machine, clone it into the pad instead and work
there — a repo you cannot read is a blocker, not a reason to improvise.

### 4 — Do the work

Ordinary engineering, in your own domain, to your own standard. Read the code around the
change before touching it. Fix the cause, not the symptom.

**Test it.** Run whatever the repo runs, and say the real result — a suite you did not run
is not a suite that passed, and a failure you found is part of your answer. If your change
fixes a bug, the repo should end up with a test that fails without your fix; if that is
genuinely not possible here, say why in the comment.

Stay inside the issue. Something else broken that you trip over goes through `/jstack:report`
— fixed in its own commit, or filed as its own issue. It does not silently ride along in
this PR.

### 5 — Commit and open the PR

```bash
git add <your files>
git commit -m "<type>: <what changed>"
git push -u origin issue-<N>
gh pr create --repo <owner/repo> --head issue-<N> --title "<title>" --body "Fixes #<N>

<what changed and why, in a few lines>"
```

`Fixes #<N>` in the body is not decoration — it is what ties the PR to the issue in
GitHub's own UI, which is where a reviewer looks.

Do not merge. Closing the issue is what merges, and that is not your call.

### 6 — Answer on the issue

```bash
gh issue comment <N> --repo <owner/repo> --body "..."
```

Short, and specific enough to act on:

- **What you changed** — behaviour, not a file tour.
- **The PR** — `#<pr>`.
- **How you know it works** — the test you ran and its actual result.
- **What you did not do** — anything in the issue you left, and why.

Then:

```bash
place-issue --repo <owner/repo> --issue <N> --status "Review"
```

### 7 — Stay at the prompt

Do not exit. A comment on the issue comes back into **this session**, and a session that
exited cannot receive one. Closing the issue merges the PR and ends this session — that is
the ending, and it is not yours to trigger.

## Blocked

Blocked is a real outcome, not a failure to hide. Anything that stops you — the brief is
unactionable, a decision is needed, credentials are missing, the fix is far larger than the
issue implies:

```bash
place-issue --repo <owner/repo> --issue <N> --status "Blocked"
gh issue comment <N> --repo <owner/repo> --body "Blocked: <what stopped you> / <exactly what you need to continue>"
```

Then stay at the prompt. The answer arrives as a comment, and it lands here.

Say *exactly* what would unblock you. "Needs clarification" wastes the round trip that
"should this apply to archived rows too, or only live ones?" would have ended.

## Failure modes (DO NOT)

- **DO NOT** branch or commit in the shared checkout. Worktree, always.
- **DO NOT** name the branch anything but `issue-<N>`. Nothing merges if you do.
- **DO NOT** merge your own PR, or close the issue.
- **DO NOT** widen the PR beyond the issue. Extra findings go through `/jstack:report`.
- **DO NOT** report a test result you did not see, or a board column you did not get.
- **DO NOT** end the session. Rest at the prompt so Boss can talk to it.
- **DO NOT** answer only in this session. If it is not on the issue, it did not happen.
