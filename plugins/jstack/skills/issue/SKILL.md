---
name: issue
description: Work a GitHub issue end to end — read it, put it on the work board, build the fix in a worktree, open the PR, answer on the issue. Runs when an issue is assigned to the agent account.
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

## 2. Board it

```bash
place-issue --repo <owner/repo> --issue <N> --status "In Progress"
```

Defaults to the Auto-Work board; `--list-boards` shows the alternatives when the work clearly belongs elsewhere. Adding is idempotent, so a resumed session does not duplicate its card. A non-zero exit means the card is not where you would say it is — report that rather than claiming a column you did not get.

## 3. Get a worktree

Branch beside the repo's checkout, never inside it:

```bash
WT=<your-seat>/pad/issue-<N>
git -C <repo-root> worktree add "$WT" -b issue-<N>     # first time
git -C <repo-root> worktree add "$WT" issue-<N>        # resume
cd "$WT"
```

Repo not on this machine → clone it into the pad and work there.

## 4. Do the work

Ordinary engineering to your own standard: read the code around the change, fix the cause. Run whatever the repo runs and report the real result. A bug fix leaves behind a test that fails without it; where that is genuinely impossible, say why in the comment.

Stay inside the issue. Anything else you trip over goes through `/jstack:report` — its own commit or its own issue, never riding along in this PR.

## 5. Commit and open the PR

```bash
git add <your files>
git commit -m "<type>: <what changed>"
git push -u origin issue-<N>
gh pr create --repo <owner/repo> --head issue-<N> --title "<title>" --body "Fixes #<N>

<what changed and why, in a few lines>"
```

`Fixes #<N>` is what ties the PR to the issue in GitHub's own UI. Do not merge and do not close the issue — closing is what merges, and it is not your call.

## 6. Answer on the issue

```bash
gh issue comment <N> --repo <owner/repo> --body "..."
place-issue --repo <owner/repo> --issue <N> --status "Review"
```

Short and specific: what changed as behaviour rather than a file tour, the PR number, the actual test result, and anything you left undone and why.

Then stay at the prompt — do not exit. A comment on the issue comes back into this session, and one that exited cannot receive it.

## Blocked

Cannot proceed — unactionable brief, decision needed, missing credentials, a fix far larger than the issue implies: follow `${CLAUDE_PLUGIN_ROOT}/skills/issue/blocked.md`.
