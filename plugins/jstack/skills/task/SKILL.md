---
name: task
description: Use when handing a unit of work to an agent — files a GitHub task issue, spawns the executor on it, and keeps the conversation in this CLI.
argument-hint: "<what needs doing, in prose>"
---

# /jstack:task

`$ARGUMENTS` is the ask. Turn it into a task issue — this is how work is handed to an agent now, and it replaces `msg --wake`. The issue is the task, its comments are the conversation, its PR is the delivery, the merge is the close. Filing makes you the **creator**: you answer the worker's questions, you review the PR, you merge.

The bar for a task is that it needs a worker: a separable unit someone can take from brief to PR. Work in front of you is yours to finish; news for another seat is `msg send`.

## 1. Compose

- **Repo** — where the work lands. Default `Jarvis-and-J/jarvis` for anything without an obvious home.
- **Title** — imperative: what done looks like, not a topic.
- **Body** — the worker's whole brief; your session's prose does not travel. Context (what exists, where, why this matters) + acceptance criteria they can be reviewed against. Digest style.
- **Type label**, exactly one: `bug` = restore claimed behaviour · `optimization` = same behaviour, better · `feature` = build what does not exist.

## 2. File

```bash
task-create --title "..." --body "..." --label feature [--repo owner/name]
```

Filing embeds this session in the issue body (the creator marker — how comments find their way back here) and then assigns the executor account. **The assignment is the spawn** — a worker starts immediately; there is nothing else to trigger.

The last line is the receipt: `TASK <url> board=… type=… assigned=… creator=…`. Report the url. Two degradations to take seriously:

- `assigned=none` with exit 6 — the issue exists but **nothing spawned**; report that with the fix-by-hand line from stderr, do not re-file.
- a "no creator session resolvable" warning — the issue filed, but comments will not reach this CLI; the thread lives on GitHub only.

## 3. Converse

Every comment on the issue lands back in this CLI — at your next stop, or by waking this conversation. Answer **on the issue**, never only in prose here:

```bash
gh issue comment <N> --repo <owner/repo> --body "..."
```

Comment style is a hard rule: digest form — what changed, what's next, what's blocked. A few lines. Boss reads these.

A "worker died (exit N)" comment means the spawn is gone, loudly. Re-assigning the executor revives the same session; do that, or say why not.

## 4. Review and merge

The PR arrives here as a comment too. Review it against the acceptance criteria you wrote:

- **Matches** — merge it (`gh pr merge`), or close the issue and the gated close-to-merge runs (draft, conflict, or failing checks never merge).
- **Falls short** — comment exactly what falls short; the worker picks it up.

Merging is a reviewed act — never merge without reading the diff against the ACs.

Cards are not your job: In Progress, Review, Blocked, Done all move process-side. Never place a card for a task.
