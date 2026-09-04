---
name: push
description: Use when the user says push, commit, ship it, or land this.
argument-hint: "[0] [all]"
---

# /jstack:push

Authorization is the user saying push / commit / ship / land in **this** session. Without it, ask — never infer.

Arguments, any order: `0` commits without pushing. `all` widens scope to every pending change in each repo touched — `${CLAUDE_PLUGIN_ROOT}/skills/push/all-mode.md`. Anything else, ask.

Concurrent sessions share the tree. A dirty tree, files you did not touch showing as pending, a sibling in the same repo — none of it is a reason to pause, ask, or postpone. Stage your own paths; leave the rest unmentioned.

## 1. Find the repos

Run `session-files`. It prints one absolute path per line: every file this session wrote that git still sees a change at. That list is authoritative — stage all of it. Add by hand only what it cannot see: writes made through Bash (`mv`, `sed -i`, a script that emits files). A non-zero exit means it could not read the transcript; say so in the report and fall back to your own tool calls. Never read a failure as "nothing to commit".

Resolve each path to its repo root, and group by what this prints:

```bash
git -C "$(dirname "$F")" rev-parse --show-toplevel
```

A path that prints nothing is not pushable — drop it, name it in the report. Nothing resolves at all → tell the user in one line and stop. Do not assume the cwd is a repo; the cockpit usually is not.

Never cross-check the list against `git status` — what is on nobody's list is another session's.

## 2. Split into units

Say the split out loud, one line per unit, before staging anything.

Side fixes first, one commit each. The deliverable next. Same feature together, distinct domains apart, pure docs / tests / data captures each alone. Generated artifacts last, as one `chore:`.

Changes touching the same lines are one unit — fold them together and name the second with an `Also-fixed:` trailer. Never fake a split with a partial stage; that commit describes a tree that never existed.

## 3. Commit each unit

Read the repo first — `git -C "$R" status`, `git -C "$R" log --oneline -5` for local convention, `git -C "$R" rev-parse --abbrev-ref HEAD`.

Stage explicitly, one unit at a time, exact paths, no globs:

```bash
git -C "$R" add <file1> <file2> ... <fileN>
```

Subject: `<type>(<scope>): <what changed, active voice>` — ≤72 chars, lowercase after the colon, no trailing period. `<type>` is exactly one of `feat` `fix` `refactor` `perf` `test` `docs` `chore`; the vocabulary is fixed so `git log --grep` stays answerable. Body after a blank line, wrapped ~80: why the change exists, then what it does, citing test counts or commit refs where they exist.

Trailers last, after a blank line: `Found-during: <task>` on a side fix · `Closes: #N` · `Refs: #N` · `Also-fixed: <what>`.

```bash
git -C "$R" commit -m "$(cat <<'EOF'
<subject>

<body>
EOF
)"
```

Never `--no-verify`, `--no-gpg-sign`, `--amend`, `git add -A`, `git add .`, a `Co-Authored-By` line, or a generated-by footer. A failing hook gets the underlying issue fixed, never bypassed.

Never stage `.env*`, `*.secrets*`, `*credentials*`, `*.pem`, `*.key`, or anything matching a common API-key pattern — skip them silently. Verify before each commit:

```bash
git -C "$R" diff --cached -- '*.env*' '*secret*' '*.pem' '*.key'
```

## 4. Push

`git -C "$R" push` per repo, unless arg `0`. Remote moved → `git -C "$R" pull --rebase`, then push again. Never force-push `main` or `master`; surface a rebase failure rather than papering over it.

## 5. Report

One line per commit — `<sha> <type>(<scope>): <subject>` — grouped under its repo and branch. No summary paragraph. Name any dropped non-repo files.

## 6. Log the sitting

Here, not at session end — by then the shas are gone.

```bash
log_event <agent>/<submode> "<why this sitting happened>" --commit <sha>@<repo-root>...
```

Link every sha; keep them out of the prose. Tag the subject if untagged. Then stop.
