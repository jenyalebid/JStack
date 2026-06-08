---
name: push
description: Commit and push work from the current session — or, with `all`, group every pending change in the repo into per-unit-of-work commits and push. Use when the user says "push", "commit", "ship it", "land this". Default scope is this session's edits only. Add `0` to commit without pushing. Add `all` to capture everything pending.
argument-hint: "[0] [all]"
---

# /jstack:push — commit + push from a session

User invoked push. Commit and push the work from this session (default) or every pending change in the repo grouped by unit of work (`all` mode).

**User said "push" / "commit" / "ship" / "land" / `/jstack:push` in THIS session = authorization.** No invocation without that. If they haven't said it in this session, do NOT invoke — ask first.

---

## Arguments

Parse `$ARGUMENTS` as a space-separated set:

| Flag combo | Scope | Push? |
|------------|-------|-------|
| (empty)    | This session's edits only | yes |
| `0`        | This session's edits only | no — commit only |
| `all`      | EVERY uncommitted change in the repo, grouped by unit of work (multiple commits) | yes |
| `0 all` or `all 0` | All changes, grouped, multiple commits | no — commit only |

Order doesn't matter. Anything else = error, ask the user to clarify.

---

## Pre-flight (always)

```bash
git rev-parse --show-toplevel                    # confirm we're in a repo
git status                                       # see the working tree
git log --oneline -5                             # match recent commit style
git rev-parse --abbrev-ref HEAD                  # branch
```

Run from the repo root (or pass `-C <root>` to git). Hard rules:

- **No `--no-verify`, no `--no-gpg-sign`, no `--amend`.** Always a NEW commit. If a hook fails, fix the underlying issue and commit again — don't bypass.
- **No `Co-Authored-By` line.**
- **No `🤖 Generated with Claude Code` footer.**
- **No `git add -A` or `git add .`** — stage explicit file lists only.
- **Sensitive paths** never staged: `.env*`, `*.secrets*`, `*credentials*`, `*.pem`, `*.key`, anything matching common API-key patterns. Skip silently if seen.
- **Never force-push to `main`/`master`.**

---

## Default (session-scoped)

You know what you touched this session. Walk the conversation:

1. **Build the file list.** From your own Edit/Write/Bash tool calls in this session, list every path you modified, created, or deleted. Include files affected by `mv`, `sed -i`, scripts you ran, or any other write you performed. If you're uncertain a file is yours, leave it out — better to land a tight commit and follow up than to scoop unrelated work.

2. **Cross-check against `git status`.** Every file on your list must appear as modified/added/deleted in the working tree. Files in `git status` but NOT on your list = other sessions' work — exclude them.

3. **Stage explicitly.**

   ```bash
   git add <file1> <file2> ... <fileN>
   ```

   No shell globs that could capture untouched files. Paste the exact paths.

4. **Draft the commit message.** Follow this repo's style (read recent `git log` to confirm):

   - Subject (≤72 chars): `<area>: <what changed in active voice>` — e.g. `auth: rename session token`, `dashboard: fix cwd resolution`, `docs: clarify install flow`.
   - Blank line.
   - Body: WHY first, then WHAT. Wrap at ~80 chars. Bullets where helpful. Include verifiable evidence (commit refs, test counts, latencies) when relevant.
   - No emojis unless the user asked.
   - No `Co-Authored-By`. No `Generated with Claude Code` footer.

5. **Commit** (HEREDOC to preserve formatting):

   ```bash
   git commit -m "$(cat <<'EOF'
   <subject>

   <body>
   EOF
   )"
   ```

6. **Push** (unless arg `0`):

   ```bash
   git push
   ```

   If the push fails because the remote moved, `git pull --rebase` then `git push`. Never force-push to `main`/`master`.

7. **Report** to the user in one line: `<sha> on <branch> — N files, +X/-Y`. Then stop.

---

## `all` mode (every pending change in the repo)

```bash
git status --short
git diff --stat HEAD
```

You're now responsible for everything pending. Group by **unit of work** — a unit is a coherent change that would land as one PR's worth of edits. Heuristics, in order of priority:

1. **Same feature/system** — files touching the same module, same service, same product feature.
2. **Same scope/domain** — distinct subprojects or areas get distinct commits.
3. **Same kind of change** — pure doc updates, pure test additions, pure data captures (CSVs/logs) can each form their own commit.
4. **Same author trail** — if you can tell from the conversation that another session or process touched a file, preserve that grouping.

Auto-generated artifacts (state files, timestamp bumps, cache files, log captures from routine jobs) get their own commit at the end labeled `chore:` — don't bury them inside a feature commit.

**Before committing anything**, write a one-line plan back to the user:

```
push plan (N commits):
  1. <area>: <subject> — <file count> files
  2. <area>: <subject> — <file count> files
  ...
```

Then execute each commit in order using the same HEREDOC pattern. After all commits land, `git push` once (skipped if arg `0`).

Report: `<N> commits, <sha-first>..<sha-last>` on the branch. Then stop.

---

## Failure modes (DO NOT)

- **DO NOT** invoke without the user explicitly saying push/commit/ship/land in this session. Inferring authorization is the cardinal sin.
- **DO NOT** scoop files from `git status` you didn't touch. A push that includes another session's WIP is worse than no push.
- **DO NOT** commit secret files. Quick check before committing: `git diff --cached -- '*.env*' '*secret*' '*.pem' '*.key'` should be empty.
- **DO NOT** include a `Co-Authored-By` footer or `Generated with Claude Code` attribution.
- **DO NOT** force-push to `main`/`master`. If push fails on rebase, surface it to the user — don't paper over.
- **DO NOT** amend a previous commit. Always a new one.
- **DO NOT** silently squash `all` mode into one commit because it feels neater. The user explicitly wants per-unit-of-work commits in `all` mode.

---

## After push

Don't write a summary paragraph. One line: `<sha> on <branch>` (default) or `<N> commits, <first-sha>..<last-sha>` (`all`). The git log is the receipt.
