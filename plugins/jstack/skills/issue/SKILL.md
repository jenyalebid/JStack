---
name: issue
description: Use when working a GitHub issue end to end, or when an issue is assigned to the agent account.
argument-hint: "<owner/repo#N>"
---

# /jstack:issue

`$ARGUMENTS` is `owner/repo#N`. Missing → ask which issue, never guess.

Take that issue from open to a PR waiting to be merged. The issue body is your whole brief, and the issue is where your answer must land — this session's prose does not survive.

Two contracts hold the machinery together. **The branch is `issue-<N>`**, exactly: closing the issue merges the open PR whose head is `issue-<N>`, and nothing else records which branch belonged to which issue. And **never switch branches in the shared checkout** — every agent on this machine shares one working tree per repo, so `git checkout -b` moves the branch under other sessions mid-edit. Use a worktree, with no exception for a small change.

## 1. Read the issue, all of it

```bash
gh issue view <N> --repo <owner/repo> --json title,body,labels,state,url,comments
```

Comments matter: a re-assignment or resume means a conversation may already be above you, and the last comment is usually the live instruction.

The type label sets the ask: `bug` = restore the claimed behaviour · `optimization` = same behaviour, faster or clearer · `feature` = build what does not exist. A body naming no symptom, surface, or ask is unactionable — go to **Blocked** rather than guessing.

Cards are not your job: In Progress, Review, Blocked, Done all move process-side on the events you fire anyway. Never place a card.

## 2. Get a worktree

Branch beside the repo's checkout, never inside it:

```bash
WT=<your-seat>/pad/issue-<N>
git -C <repo-root> worktree add "$WT" -b issue-<N>     # first time
git -C <repo-root> worktree add "$WT" issue-<N>        # resume
cd "$WT"
```

Repo not on this machine → clone it into the pad and work there.

## 3. Do the work

Ordinary engineering to your own standard: read the code around the change, fix the cause. Run whatever the repo runs and report the real result. A bug fix leaves behind a test that fails without it; where that is genuinely impossible, say why in the comment.

Comment as you go. When the shape of the fix settles, when you change course, when something surprises you — put it on the issue, not in this session's prose. Comment style is a hard rule: digest form — what changed, what's next, what's blocked. A few lines. The user reads these.

Stay inside the issue. Anything else you trip over goes through `/jstack:report` — its own commit or its own issue, never riding along in this PR.

## 4. Commit and open the PR

```bash
git add <your files>
git commit -m "<type>: <what changed>"
git push -u origin issue-<N>
gh pr create --repo <owner/repo> --head issue-<N> --title "<title>" --body "Fixes #<N>

<what changed and why, in a few lines>"
```

`Fixes #<N>` is what ties the PR to the issue in GitHub's own UI. Do not merge and do not close the issue — closing is what merges, and it is not your call.

## 5. Answer on the issue

```bash
gh issue comment <N> --repo <owner/repo> --body "..."
```

Short and specific: what changed as behaviour rather than a file tour, the PR number, the actual test result, and anything you left undone and why.

Your turn can end here. A later comment on the issue resumes this conversation — read it as the live instruction and answer it on the issue again.

## Blocked

Cannot proceed — unactionable brief, decision needed, missing credentials, a fix far larger than the issue implies: follow `${CLAUDE_PLUGIN_ROOT}/skills/issue/blocked.md`.
