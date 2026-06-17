---
name: audit
description: Use when you want this session's work independently checked before trusting it's done — a trust-nothing reviewer verifies every claim from source. Default `internal` mode reports back in this session; add `external` to run it in a separate terminal you drive yourself.
argument-hint: "[focus] [@agent] [internal|external]"
---

# /jstack:audit — adversarial audit of this session's work

A handoff doc is a continuation briefing. An audit brief is its inverse — a **claims document**: here's what this session says it did, and the auditor's job is to verify every claim from source. The auditor has fresh eyes and no investment in the work being correct; that separation is the point.

Two modes, same trust-nothing core:

- **`internal` (default)** — the auditor runs as a **subagent of this session**. It returns *structured* findings to this model. This model then **independently re-verifies each finding from source**, fixes the ones it confirms real, refutes the noise, flags the genuinely-unclear ones, and hands Boss a **condensed report**. No wall of raw auditor text — Boss reads a triaged verdict, not a transcript.
- **`external`** — opens a fresh terminal preloaded with the brief; the auditor reports its verdict to Boss *in that terminal*. Use when Boss wants to drive the audit himself with full context separation.

## Arguments

`$ARGUMENTS` = `[focus] [@agent] [internal|external]`, all optional, order-agnostic.

- **`internal` / `external`** (the mode token): selects the mode. Default `internal` if absent.
- **`@agent`** (the `@`-prefixed token, wherever it appears): run the audit under a different agent's identity. Resolve the target workspace under `${user_config.agent_root}`: match `{Name}` against agent subdirectories case-insensitively (`@mario` → `Mario/`). Target cwd = the agent's `chat/` subdir if it exists, else the agent root. No matching directory → list the available agent directories and stop; do not guess.
- **`focus`** (everything that isn't a recognized token): narrow the audit to that part of the work. The brief covers only claims relevant to the focus and the auditor goes deep on it. Omitted → audit everything this session claims to have done.

With no `@agent`, the target cwd is the current cwd.

## Step 1 — Write the audit brief (both modes)

Reflect on this entire conversation and write the brief. You are the session being audited — **the brief's value is proportional to its honesty.** Overselling what was verified, omitting shortcuts, or softening user constraints defeats the audit and will be exposed anyway, since the auditor verifies everything from source. Say what you actually did, checked, and didn't.

Rules:

- Absolute paths everywhere — the auditor may boot in a different cwd.
- Name the repo, branch, and commit range (or "uncommitted working tree") so the auditor can derive the real diff.
- **Caution Flags is mandatory and verbatim.** Every constraint the user stated — "be careful not to break X", "don't touch Y", "keep Z working" — quoted in their words. If the user stated none, write "None stated by user" and add the session's own assessment of the riskiest thing the changes could have broken.
- Keep the whole file under 150 lines — in external mode it rides in system-prompt space.

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
6. **Report only — change nothing.** No fixes, however small. You produce
   findings; the deciding party (the parent session in internal mode, the user
   in external mode) decides what happens.

Every finding must be a falsifiable claim with: a SEVERITY (high/med/low), the
EVIDENCE that grounds it (file:line, command + output, or why it's
unverifiable), and the SO-WHAT (the concrete risk if it's real). A finding
without evidence is not a finding — drop it or mark it UNVERIFIABLE.

Verdict format:

- Per claim (including every Caution Flag): **CONFIRMED** / **REFUTED** /
  **UNVERIFIABLE**, each with its evidence.
- Then findings the brief never claimed — regressions, undeclared changes,
  broken consumers — ranked by severity, each with evidence and so-what.
- One-line overall verdict at the top: clean, or N findings worth attention.

If something genuinely blocks the audit before it starts — missing access, a
repo path that doesn't exist, scope you cannot determine — ask now. Otherwise
begin immediately; do not wait for input or ask permission to proceed.

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

Write the file to `{TARGET_CWD}/audit-brief.md` with the Write tool (target cwd from Arguments — current cwd unless `@agent` redirected it). If a prior brief exists there, remove it first so the Write is a fresh create:

```bash
trash "$TARGET_CWD/audit-brief.md" 2>/dev/null || rm -f "$TARGET_CWD/audit-brief.md"
```

Then output the **brief part** (not the protocol boilerplate) to Boss so he can correct a wrong premise. In external mode, wait a beat for correction. In internal mode, proceed immediately — the triage step catches a slightly-off premise, and Boss can interrupt.

## Step 2 (internal mode) — Dispatch the auditor subagent

Spawn one `general-purpose` agent via the Agent tool, pointed at the brief. It must read the file, follow the Audit Protocol, and **return its findings as structured text** — not prose. For a large diff, dispatch several in parallel split by area (e.g. correctness, blast radius, the Caution Flags) and merge their findings; otherwise one deep auditor.

Kickoff prompt for the subagent:

> You are an adversarial auditor. Read `{TARGET_CWD}/audit-brief.md` in full — it
> contains an Audit Protocol and an Audit Brief. Follow the protocol exactly:
> believe nothing in the brief, verify every claim from source (code, diffs,
> builds, test runs), and change NOTHING. Return ONLY a findings list. For each
> finding output: `[SEVERITY] <one-line claim> — evidence: <file:line / command
> + output / why unverifiable> — so-what: <concrete risk>`. Group as (a) per-claim
> verdicts CONFIRMED/REFUTED/UNVERIFIABLE, (b) findings the brief never claimed.
> Lead with a one-line overall verdict. No narrative, no recap of the brief.

## Step 3 (internal mode) — Triage each finding yourself

This is the point of internal mode. The auditor's findings are **input, not verdict** — you trust the auditor no more than it trusted the brief. For every finding, **re-verify it independently from source**: open the actual file, run the actual command, read the actual consumer. Then classify:

- **REAL** — your own check confirms the issue. Fix it. The fix is justified by *your verification of the issue*, never by "the auditor flagged it." Re-verify the fix (build/test/read the result).
- **REFUTED** — your own check shows it's not an issue (auditor misread, stale line, false positive). Drop it, and record the one-line source evidence that refutes it.
- **UNCLEAR** — you can't determine it from source, or it's a judgment call / depends on intent (e.g. "is this the behavior Boss wanted?"). **Do not silently drop it and do not blind-fix it.** Surface it to Boss as a question.

Hard rules:

- **No action on the auditor's word alone.** If you couldn't independently confirm the issue, you don't fix it — you refute it or flag it UNCLEAR.
- **No silent drops.** Every finding the auditor raised appears in the report under exactly one of fixed / refuted / needs-you. Hiding a finding is the bug this skill exists to prevent.
- **A fix that touches a Caution Flag area stops and asks first**, even if the issue is real.

## Step 4 (internal mode) — Condensed report to Boss

Deliver in this session, scannable, no transcript:

- **Verdict** — one line (clean, or N real issues / M refuted).
- **Fixed** — per real issue: what it was, the fix, how you verified the fix. (file:line each.)
- **Refuted** — per dismissed finding: one line, what the auditor claimed + why it's not real.
- **Needs you** — unclear / judgment-call findings, as direct questions.

Boss reads a triaged verdict and pushes back on any line — that's the back-and-forth. Leave `audit-brief.md` in place as the record.

## External mode — open the auditor terminal (replaces Steps 2–4)

Call the bundled terminal-open adapter (on PATH while jstack is enabled). The auditor must start on arrival, so pass a kickoff prompt as a positional `claude` argument. The adapter flattens its args into a shell string (`ARGS="$*"`), so the multi-word prompt must carry its own quoting — wrap it in escaped double quotes inside the arg:

```bash
open-terminal-here "$TARGET_CWD" --append-system-prompt-file "$TARGET_CWD/audit-brief.md" "\"Audit session. Your system prompt carries an Audit Protocol and an Audit Brief. Follow the protocol: if genuinely blocked, ask now; otherwise begin the audit immediately and report your verdict here.\""
```

**If the adapter exits nonzero** (no supported terminal, unsupported platform), tell Boss:

> Couldn't open a new terminal automatically. Audit brief is at `<target cwd>/audit-brief.md`. Open a new Claude session there manually with `--append-system-prompt-file audit-brief.md` and tell it to begin the audit.

The brief lives in the target workspace so each agent keeps its own. The new session loads the CLAUDE.md walk-up from the target cwd — same agent for a plain audit, the target agent's identity for an `@agent` audit.
