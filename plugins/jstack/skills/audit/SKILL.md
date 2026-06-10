---
name: audit
description: Audit this session's work in a fresh terminal — a trust-nothing reviewer independently verifies every claim from source, with explicit "don't break X" constraints verified first.
argument-hint: "[focus] [@agent]"
---

# /jstack:audit — adversarial audit of this session's work in a fresh terminal

User invoked audit. Like `/jstack:handoff`, this opens a new Claude Code session in a fresh terminal preloaded with a doc — but the intent is inverted. A handoff doc is a continuation briefing: here's where we are, keep going. An audit brief is a **claims document**: here's what this session says it did, and the new session's job is to verify every claim from source. The auditor has fresh eyes and no investment in the work being correct — that separation is the point.

## Arguments

`$ARGUMENTS` = `[focus] [@agent]`, both optional, order-agnostic.

- **`@agent`** (the `@`-prefixed token, wherever it appears): run the audit under a different agent's identity. Resolve the target workspace under `${user_config.agent_root}`: match `{Name}` against the agent subdirectories case-insensitively (`@mario` → `Mario/`). Target cwd = the agent's `chat/` subdirectory if it exists, else the agent root. If no matching directory exists, list the available agent directories and stop — do not guess.
- **`focus`** (everything that isn't the `@agent` token): narrow the audit to that part of the session's work. The brief covers only claims relevant to the focus; the auditor goes deep on it instead of wide on everything. If omitted: audit everything this session claims to have done.

With no `@agent`, the target cwd is the current cwd.

## Step 1 — Write the audit brief

Reflect on this entire conversation and write the brief. You are the session being audited — **the brief's value is proportional to its honesty**. Overselling what was verified, omitting shortcuts, or softening user constraints defeats the audit and will be exposed anyway, since the auditor verifies everything from source. Say what you actually did, what you actually checked, and what you didn't.

Rules:

- Absolute paths everywhere — the auditor may boot in a different cwd.
- Name the repo, branch, and commit range (or "uncommitted working tree") so the auditor can derive the real diff.
- **Caution Flags is mandatory and verbatim.** Every constraint the user stated — "be careful not to break X", "don't touch Y", "keep Z working" — quoted in their words. If the user stated none, write "None stated by user" and add the session's own assessment of the riskiest thing the changes could have broken.
- Keep the whole file under 150 lines — it rides in system prompt space.

The file has two parts: the **Audit Protocol** (fixed text below — copy it verbatim) followed by the **brief** (your content). The protocol is the auditor's operating contract; the brief is the claims under test.

```markdown
# Audit Protocol

You are the auditor. The brief below was written by the session whose work you
are auditing. The cornerstone rule: **believe nothing in it.** Every statement
is a claim, not a fact. The brief tells you where to look — never what's true.
Verify from source: actual code, actual diffs, actual builds, actual test runs,
actual rendered output. A claim you couldn't check stays UNVERIFIABLE — never
promote it to confirmed because it sounds plausible.

Procedure:

1. **Start with Caution Flags.** Each one is a constraint the user stated
   explicitly. Verify each independently, with evidence, before anything else.
2. **Derive the real diff.** Use the named repo/branch/commits to compute what
   actually changed. Compare against "What Was Done" — undeclared changes are
   themselves findings.
3. **Derive your own blast radius — don't trust the claimed one.** For every
   changed symbol, find its consumers: direct callers, and dynamic dispatch the
   grep for call sites misses (ternaries, closures, stored function values,
   protocol/interface conformances). Verify that untouched code depending on
   touched code still behaves.
4. **Re-run claimed verifications.** "Tests pass" means you ran them. "Verified
   on sim" means you looked. If a claimed verification can't be re-run, say so.
5. **Use the instruments available.** If a /code-review command exists, run it
   on the diff as one input — it is an instrument, not the verdict. Run the
   project's test surfaces. Build and run where applicable.
6. **Report only — change nothing.** No fixes, however small. The user is in
   this terminal and decides what happens next.

Verdict format — deliver in the terminal when done:

- Per claim (including every Caution Flag): **CONFIRMED** / **REFUTED** /
  **UNVERIFIABLE**, each with evidence (file:line, command output, or why it
  couldn't be checked).
- Then findings the brief never claimed — regressions, undeclared changes,
  broken consumers — ranked by severity.
- One-line overall verdict at the top: clean, or N findings worth attention.

If something genuinely blocks the audit before it starts — missing access, a
repo path that doesn't exist, scope you cannot determine — ask the user now.
Otherwise begin immediately; do not wait for input or ask permission to proceed.

---

# Audit Brief

## Original Issue
What was asked, in the requester's words. What "done" was supposed to look like.

## What Was Done
Claimed changes: repo, branch, commit range (or uncommitted), files touched,
and what changed in each. Specific enough that every claim is checkable.

## Claimed Verifications
What this session says it tested and HOW (built? ran tests? sim? eyeballed the
code only?). Be explicit about what was NOT verified.

## Caution Flags
User-stated constraints, verbatim. If none: "None stated by user" + the
session's own top risk.

## Blast Radius (claimed)
What this session believes consumes or depends on the changed code.

## Potential Pitfalls
Shortcuts taken, weak spots, anything this session is itself unsure about.
```

## Step 2 — Write the file

Write to `{TARGET_CWD}/audit-brief.md` using the Write tool (target cwd from the Arguments section — current cwd unless `@agent` redirected it).

If a prior `audit-brief.md` exists there, remove it FIRST so the Write is a fresh-file create:

```bash
trash "$TARGET_CWD/audit-brief.md" 2>/dev/null || rm -f "$TARGET_CWD/audit-brief.md"
```

Then Write the new content (protocol + brief, one file).

## Step 3 — Show the brief

Output the brief part (not the protocol boilerplate) to the user so they can correct it before the auditor spends time on a wrong premise.

## Step 4 — Open the auditor session

Call the bundled terminal-open adapter (on PATH while jstack is enabled). The auditor must start working on arrival, so pass a kickoff prompt as a positional `claude` argument. The adapter flattens its args into a shell string (`ARGS="$*"`), so the multi-word prompt must carry its own quoting — wrap it in escaped double quotes inside the arg:

```bash
open-terminal-here "$TARGET_CWD" --append-system-prompt-file "$TARGET_CWD/audit-brief.md" "\"Audit session. Your system prompt carries an Audit Protocol and an Audit Brief. Follow the protocol: if genuinely blocked, ask now; otherwise begin the audit immediately.\""
```

**If the adapter exits nonzero** (no supported terminal found, or an unsupported platform), tell the user:

> Couldn't open a new terminal automatically. Audit brief is at `<target cwd>/audit-brief.md`. Open a new Claude session there manually with `--append-system-prompt-file audit-brief.md` and tell it to begin the audit.

The brief lives in the target workspace so each agent keeps its own. The new session loads the CLAUDE.md walk-up from the target cwd — same agent for a plain audit, the target agent's identity for an `@agent` audit.
