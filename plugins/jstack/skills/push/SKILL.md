---
name: push
description: Commit and push the work from this session — to whatever repo(s) the files you touched live in. Works from anywhere, including an agent cockpit that isn't itself a repo. With `all`, sweep every pending change in those repos into per-unit-of-work commits. Use when the user says "push", "commit", "ship it", "land this". Add `0` to commit without pushing. Add `all` to capture everything pending.
argument-hint: "[0] [all]"
---

# /jstack:push — commit + push from a session

User invoked push. Commit and push the work from this session (default) or every pending change (`all` mode) — to **whatever repos the work lives in**.

You do not need to be standing in a git repo. Agents work from a cockpit and edit code in sibling repos; this skill figures out which repos those are from the files you touched and operates on each with `git -C <repo>`. The cockpit itself need not be (and usually isn't) a repo.

**User said "push" / "commit" / "ship" / "land" / `/jstack:push` in THIS session = authorization.** No invocation without that. If they haven't said it in this session, do NOT invoke — ask first.

---

## Arguments

Parse `$ARGUMENTS` as a space-separated set:

| Flag combo | Scope | Push? |
|------------|-------|-------|
| (empty)    | This session's edits only | yes |
| `0`        | This session's edits only | no — commit only |
| `all`      | EVERY uncommitted change in each repo you touched, grouped by unit of work | yes |
| `0 all` or `all 0` | All changes, grouped, multiple commits | no — commit only |

Order doesn't matter. Anything else = error, ask the user to clarify.

---

## Step 1 — find the repos (always)

Build the touched-file list, then resolve each file to its repo. Do NOT assume the current directory is a repo.

1. **Build the file list.** From your own Edit/Write/Bash tool calls in this session, list every absolute path you modified, created, or deleted. Include files affected by `mv`, `sed -i`, scripts you ran, or any other write you performed. If you're uncertain a file is yours, leave it out — a tight commit plus a follow-up beats scooping unrelated work.

2. **Resolve each file to its repo root.** For every touched path `F`:

   ```bash
   git -C "$(dirname "$F")" rev-parse --show-toplevel 2>/dev/null
   ```

   Group files by the repo root that command prints. A file that prints nothing (not inside any repo — e.g. a cockpit note, a memory file) is **not pushable**: drop it and remember it for the report.

3. **Decide what to act on.**
   - **No touched file resolves to a repo** → nothing to push. Tell the user in one line ("nothing pushable — none of this session's edits are inside a git repo; <list>") and stop. Do not error out with a raw git message.
   - **One or more repos** → proceed. You may be committing to several repos in one invocation; that's expected and fine.

Hard rules (apply in every repo):

- **No `--no-verify`, no `--no-gpg-sign`, no `--amend`.** Always a NEW commit. If a hook fails, fix the underlying issue and commit again — don't bypass.
- **No `Co-Authored-By` line. No `🤖 Generated with Claude Code` footer.**
- **No `git add -A` or `git add .`** — stage explicit file lists only.
- **Sensitive paths** never staged: `.env*`, `*.secrets*`, `*credentials*`, `*.pem`, `*.key`, anything matching common API-key patterns. Skip silently if seen.
- **Never force-push to `main`/`master`.**

---

## Default (session-scoped)

For **each repo** `R` from Step 1, in turn:

1. **Read its context** (every git call is scoped with `-C "$R"`):

   ```bash
   git -C "$R" status
   git -C "$R" log --oneline -5          # match THIS repo's commit style
   git -C "$R" rev-parse --abbrev-ref HEAD
   ```

2. **Cross-check.** Every file you're about to stage for `R` must appear as modified/added/deleted in `git -C "$R" status`. Files in status but NOT on your list = other sessions' work — exclude them.

3. **Stage explicitly** (absolute paths are fine with `-C`):

   ```bash
   git -C "$R" add <file1> <file2> ... <fileN>
   ```

   No shell globs that could capture untouched files. Paste the exact paths.

4. **Draft the commit message** in *this repo's* style (you just read its log):

   - Subject (≤72 chars): `<area>: <what changed in active voice>` — e.g. `auth: rename session token`, `dashboard: fix cwd resolution`.
   - Blank line. Body: WHY first, then WHAT. Wrap ~80 chars. Bullets where helpful. Verifiable evidence (commit refs, test counts) when relevant.
   - No emojis unless the user asked. No `Co-Authored-By`, no `Generated with Claude Code` footer.

5. **Commit** (HEREDOC preserves formatting):

   ```bash
   git -C "$R" commit -m "$(cat <<'EOF'
   <subject>

   <body>
   EOF
   )"
   ```

6. **Push** (unless arg `0`):

   ```bash
   git -C "$R" push
   ```

   If the push fails because the remote moved, `git -C "$R" pull --rebase` then push again. Never force-push to `main`/`master`.

7. After all repos are done, **report** one line per repo: `<sha> on <branch> in <repo-name> — N files, +X/-Y`. Note any dropped non-repo files. Then stop.

---

## `all` mode (every pending change in each repo you touched)

Determine the repos the same way (Step 1). If the session touched no repo but the **current directory is itself a repo**, use that one. Then for each repo:

```bash
git -C "$R" status --short
git -C "$R" diff --stat HEAD
```

You're now responsible for everything pending in `R`. Group by **unit of work** — a coherent change that would land as one PR's worth of edits:

1. **Same feature/system** — files touching the same module/service/feature.
2. **Same scope/domain** — distinct subprojects or areas get distinct commits.
3. **Same kind of change** — pure docs, pure tests, pure data captures (CSVs/logs) each form their own commit.
4. **Same author trail** — if you can tell another session or process touched a file, preserve that grouping.

Auto-generated artifacts (state files, timestamp bumps, cache files, routine-job log captures) get their own `chore:` commit at the end — don't bury them in a feature commit.

**Before committing anything**, write a one-line plan back to the user, repo by repo:

```
push plan:
  <repo-a> (N commits):
    1. <area>: <subject> — <file count> files
    2. ...
  <repo-b> (M commits):
    1. ...
```

Then execute each commit in order with the same `-C "$R"` HEREDOC pattern. After all commits in a repo land, `git -C "$R" push` once (skipped if arg `0`).

Report: per repo, `<N> commits, <sha-first>..<sha-last> on <branch> in <repo-name>`. Then stop.

---

## Failure modes (DO NOT)

- **DO NOT** invoke without the user explicitly saying push/commit/ship/land in this session. Inferring authorization is the cardinal sin.
- **DO NOT** assume the current directory is the repo. Resolve repos from the files you touched. The cockpit is usually not a repo.
- **DO NOT** scoop files from `git status` you didn't touch. A push that includes another session's WIP is worse than no push.
- **DO NOT** commit secret files. Quick check before committing in each repo: `git -C "$R" diff --cached -- '*.env*' '*secret*' '*.pem' '*.key'` should be empty.
- **DO NOT** include a `Co-Authored-By` footer or `Generated with Claude Code` attribution.
- **DO NOT** force-push to `main`/`master`. If push fails on rebase, surface it — don't paper over.
- **DO NOT** amend a previous commit. Always a new one.
- **DO NOT** silently squash `all` mode into one commit because it feels neater. The user wants per-unit-of-work commits.

---

## After push

Don't write a summary paragraph. One line per repo: `<sha> on <branch> in <repo>` (default) or `<N> commits, <first-sha>..<last-sha> in <repo>` (`all`). The git log is the receipt.
