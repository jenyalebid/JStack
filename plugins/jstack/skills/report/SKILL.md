---
name: report
description: Close out a task — settle every finding as a commit or a filed issue, then report the result in the standard shape. Use at the end of any task that produced work.
argument-hint: "[draft]"
---

# /jstack:report

`draft` = triage and show; file and commit nothing.

## 1. Settle every finding

A finding is a confirmed defect. Nitpicks, taste calls and unconfirmed suspicions get no commit, no issue, no report line.

Fix it if the fix is reachable in the tree you are standing in. File only what you did not fix, and put the reason in the body. Fix written but blocked on a permission you lack — file it, then:

`ping_boss blocker "SYSTEM FIX BLOCKED — <file> / <cost until it lands> / #<N>"`

Filing procedure: `filing.md`.

## 2. Commit

Run `/jstack:push`. Name the split first: side fixes as their own units before the main work, the deliverable next, generated artifacts last.

## 3. Report

Only blocks that have content. No narration.

`his question` (one per question he asked) · `Blocker` — what's needed, from whom · `Issues` — `#N — title` · `Fixed` — `sha — what` · `Done` · `Not Done` — each carries `#N` or a blocker · `Next Move`

Before sending, check: every **Issues** line carries `#N`, every **Fixed** line carries a sha, no finding sits in another block's prose. Nothing found — send `Done` alone.
