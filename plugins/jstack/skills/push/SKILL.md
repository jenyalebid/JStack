---
name: push
description: Commit and push this session's work to whatever repo(s) the files it touched live in. Use when the user says "push", "commit", "ship it", or "land this".
argument-hint: "[0] [all]"
---

# /jstack:push — commit + push from a session

User invoked push. Commit and push the work from this session (default) or every pending change (`all` mode) — to **whatever repos the work lives in**.

You do not need to be standing in a git repo. Agents work from a cockpit and edit code in sibling repos; this skill figures out which repos those are from the files you touched and operates on each with `git -C <repo>`. The cockpit itself need not be (and usually isn't) a repo.

**User said "push" / "commit" / "ship" / "land" / `/jstack:push` in THIS session = authorization.** No invocation without that. If they haven't said it in this session, do NOT invoke — ask first.

**Concurrent sessions are normal.** Agents share a working tree; several are usually mid-edit while you commit. A dirty tree, files you didn't touch showing as pending, a sibling working the same repo — none of it is a reason to pause, ask, or postpone. Stage your own paths explicitly (Step 3) and a commit lands only those. Commit and push your work; don't list, count, or narrate the rest in your report. The ask was for the result, not the traffic.

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

1. **Get the file list — do not reconstruct it.** Run `session-files`. It reads this session's own transcript and prints one absolute path per line: every file you wrote that git still sees a change at, ready to stage.

   That list is authoritative and you stage all of it. It is built from your own tool calls, never from the working tree, so another session's pending changes cannot appear in it no matter how dirty the tree is — and "I'm not sure this one is mine" is not a question you have to answer. Empty output from a clean run means there is genuinely nothing to commit.

   Two things it cannot see, and they are the only paths you add by hand:
   - **Writes made through Bash** — `mv`, `sed -i`, a script that emits files. Those never became tool calls, so no transcript records them.
   - **Files you wrote before a `/compact`** are still in the transcript and still listed — trust the list over your own recollection, which is the part that got summarized away.

   If `session-files` exits non-zero it could not read your transcript (no session id, no matching file). Say so in your report and fall back to listing paths from your own tool calls — never treat a failed run as "nothing to commit".

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

2. **Do not cross-check the list against `git status`.** `session-files` already restricted it to paths git sees a change at, so re-testing them against the tree only hands back the judgment call it exists to remove. Check only the paths you added by hand in Step 1. Anything in `status` that is on nobody's list is another session's work — leave it, silently.

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
- **DO NOT** scoop files from `git status` you didn't touch — commit yours, leave theirs. That is the whole of it: no pausing over them, no asking about them, no reporting them back.
- **DO NOT** commit secret files. Quick check before committing in each repo: `git -C "$R" diff --cached -- '*.env*' '*secret*' '*.pem' '*.key'` should be empty.
- **DO NOT** include a `Co-Authored-By` footer or `Generated with Claude Code` attribution.
- **DO NOT** force-push to `main`/`master`. If push fails on rebase, surface it — don't paper over.
- **DO NOT** amend a previous commit. Always a new one.
- **DO NOT** silently squash `all` mode into one commit because it feels neater. The user wants per-unit-of-work commits.

---

## After push

Don't write a summary paragraph. One line per repo: `<sha> on <branch> in <repo>` (default) or `<N> commits, <first-sha>..<last-sha> in <repo>` (`all`). The git log is the receipt.
