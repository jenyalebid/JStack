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

## The commit contract (both modes)

Git is the project's timeline. `git log --oneline` should read as the story of the work — which means a fixed vocabulary in the subject and the detail pushed into trailers.

### Group into units of work first

A commit is one coherent change. Before staging anything, split what you have:

1. **Side fixes land first, one commit each.** A break you repaired on the way to the real task is its own unit, committed *before* the main work. History then reads *ground fixed, then thing built* — and the fix stays findable when the feature it enabled is long forgotten.
2. **The deliverable** — the thing you were asked for — is one unit.
3. **Same feature/system** — files touching one module/service/feature go together.
4. **Same scope/domain** — distinct subprojects get distinct commits.
5. **Pure docs, pure tests, pure data captures** — each its own commit.
6. **Generated artifacts** (state files, timestamp bumps, caches, job log captures) — one `chore:` commit, last. Never buried in a feature commit.

If two changes genuinely touch the same lines, they are one unit. Faking a split with a partial stage produces a commit that never existed as a working tree — don't. Fold it in and name it with an `Also-fixed:` trailer.

### Subject

```
<type>(<scope>): <what changed, active voice>
```

≤72 chars, lowercase after the colon, no trailing period. `<scope>` is the area — a module, service, or surface. `<type>` is one of exactly these:

| type | for |
|---|---|
| `feat` | new capability |
| `fix` | a defect repaired |
| `refactor` | structure changed, behaviour identical |
| `perf` | faster or lighter, behaviour identical |
| `test` | tests only |
| `docs` | documentation only |
| `chore` | generated artifacts, config, housekeeping |

The vocabulary is fixed on purpose: `git log --oneline | grep ' fix('` is only a useful question if `fix` always means the same thing.

### Body — why first, then what

Blank line after the subject. Wrap ~80 chars. Lead with **why this change exists**, then what it does. Bullets where they help. Cite verifiable evidence — test counts, commit refs, the measurement — when there is any.

### Trailers

Last block, after a blank line. Git-native, so they stay greppable (`git log --grep`) and machine-readable (`git interpret-trailers`):

| trailer | when |
|---|---|
| `Found-during: <task>` | a side fix — records what you were actually doing when it surfaced |
| `Closes: #N` | this commit resolves that issue |
| `Refs: #N` | related, does not close it |
| `Also-fixed: <what>` | a fix that could not be split out of this commit |

Never `Co-Authored-By`. Never a generated-by footer.

### Example

```
fix(session-files): resolve pad symlinks before staging

Every seat's pad is a symlink into the home repo. `git -C` follows it, but the
unresolved /private/tmp pathspec is refused as outside-repo — and the refusal
was swallowed as "nothing changed". Any session that wrote to its pad and edited
repo files got a silently empty stage list.

Resolve with realpath before the pathspec is built, and fail loud if git still
refuses. Proved red by mutation; 17 tests.

Found-during: xcode ACP seat cwd inversion
Closes: #41
```

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

3. **Split the repo's files into units of work** per **The commit contract** above. One unit is usually the whole answer; a session that fixed something on the way to the main task has at least two, and the side fix commits first. Say the split out loud in one line per unit before you stage — a split you never named is a split you didn't make.

4. **Stage one unit explicitly** (absolute paths are fine with `-C`):

   ```bash
   git -C "$R" add <file1> <file2> ... <fileN>
   ```

   No shell globs that could capture untouched files. Paste the exact paths. Stage only the unit you are about to commit, never the whole session's list at once.

5. **Draft the commit message** to **The commit contract** — `<type>(<scope>): subject`, why-first body, trailers. Add `Found-during:` on a side fix and `Closes: #N` when it resolves a filed issue. Read this repo's recent log for local conventions the contract doesn't cover.

6. **Commit** (HEREDOC preserves formatting):

   ```bash
   git -C "$R" commit -m "$(cat <<'EOF'
   <subject>

   <body>
   EOF
   )"
   ```

7. **Repeat 4–6 for each remaining unit**, in contract order: side fixes, then the deliverable, then `chore:` artifacts last.

8. **Push** (unless arg `0`):

   ```bash
   git -C "$R" push
   ```

   If the push fails because the remote moved, `git -C "$R" pull --rebase` then push again. Never force-push to `main`/`master`.

9. After all repos are done, **report** one line per commit: `<sha> <type>(<scope>): <subject>`, grouped by repo, with the branch. Note any dropped non-repo files. Then stop.

---

## `all` mode (every pending change in each repo you touched)

Determine the repos the same way (Step 1). If the session touched no repo but the **current directory is itself a repo**, use that one. Then for each repo:

```bash
git -C "$R" status --short
git -C "$R" diff --stat HEAD
```

You're now responsible for everything pending in `R`. Group by **unit of work** exactly as **The commit contract** defines it, plus one rule that only applies here:

- **Same author trail** — if you can tell another session or process touched a file, preserve that grouping rather than merging it into yours.

`all` differs from the default only in **scope** — everything pending versus this session's edits. The grouping, the subject vocabulary, and the trailers are the same contract in both modes.

**Before committing anything**, write a one-line plan back to the user, repo by repo:

```
push plan:
  <repo-a> (N commits):
    1. <type>(<scope>): <subject> — <file count> files
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
- **DO NOT** silently squash into one commit because it feels neater — in either mode. A side fix folded into the feature commit that carried it is invisible the moment anyone looks for it.
- **DO NOT** invent a `<type>` outside the seven in the contract. An unknown type makes the log unqueryable, which is the only reason the vocabulary is fixed.

---

## After push

Don't write a summary paragraph. One line per commit — `<sha> <type>(<scope>): <subject>` — grouped under its repo and branch. The git log is the receipt.
