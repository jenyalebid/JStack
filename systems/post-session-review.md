# Post-Session Review — Architecture Spec

A small automated pass that runs immediately after a Claude Code session ends. Its job is to keep the agent's state files honest about what just happened — so the next session boots from truth, not a stale snapshot.

This doc describes the pattern. You build the implementation against your machine.

---

## 1. The problem it solves

A session runs for an hour. The model touches files, makes decisions, defers some threads, drops others. When it ends:

- `state.md` and `active/*.md` may not reflect what actually happened
- Threads the user mentioned mid-session that didn't get addressed are now invisible
- Time-sensitive follow-ups have no system carrying them forward
- The next session reads stale truth and re-litigates settled decisions

Without a review pass, every session degrades the reliability of state files until they're worse than no record at all. **A wrong record is more dangerous than no record** — the next session trusts it.

Review reconciles. Once per session. Fast, small, deterministic.

---

## 2. The pattern

```
session ends
    ↓
hook fires
    ↓
spawn a fresh review session (separate process, fresh context)
    ↓
review reads:
    - the JSONL of the session that just ended
    - the agent's state files (state.md, active/*.md, any others)
    - whatever external signal sources matter (timeline log, git log, scheduled-job state)
    ↓
review decides:
    - did the user direct work that hasn't landed in state? → reconcile
    - did a thread get dropped silently? → surface it (file a follow-up artifact)
    - did the session contradict an active item's status? → update or close it
    - did a decision change that should be captured? → record it
    ↓
review writes (only where reconciliation is needed):
    - updated state.md
    - updated/closed active items
    - new artifacts representing dropped threads or follow-ups
    ↓
review exits
```

The review session is **not** a continuation of the original session. It's a fresh process with no memory beyond what it reads from disk + the just-ended session's JSONL.

---

## 3. The trigger

Claude Code emits a session-end signal. You hook it.

Two viable hook surfaces:

- **Claude Code's `Stop` hook** (settings.json `hooks.Stop`) — fires when a session ends in interactive mode. Cleanest because Claude Code owns it natively.
- **External watcher** — a process that watches `~/.claude/projects/*/`  for newly-modified JSONL files and fires when one stops being written for ≥N seconds. Catches sessions Claude Code's hook missed (e.g. crashed processes, `claude --print` runs).

Either way, the hook payload includes the session ID and JSONL path. That's the input to the review.

---

## 4. The recursion problem

The review pass IS a Claude Code session. Its own session-end will trigger the hook again, which will spawn another review, which triggers the hook, and so on.

You need a recursion guard. Two patterns:

- **Environment variable** — set `SKIP_SESSION_HOOK=1` when spawning the review session. The hook checks the env var early and exits if set.
- **CWD-based exclusion** — review sessions run in a known cwd (e.g. `~/Agents/{Name}/review/`). The hook checks the just-ended session's cwd and skips if it matches.

Env var is more robust (works regardless of cwd). Use it.

---

## 5. The review session itself

It runs as a Claude Code session, with a `CLAUDE.md` that defines its job. Typically:

- A dedicated sub-mode dir for the agent: `~/Agents/{Name}/review/` with its own `CLAUDE.md`
- The hook invokes: `claude --print -p "review session $SESSION_ID" --cwd ~/Agents/{Name}/review/` (or equivalent for your spawn mechanism)
- The cwd's `CLAUDE.md` carries the review procedure (what to read, what to reconcile, what to write)

Keep the procedure focused. Review is reconciliation, not work. If the review session starts editing source code, you've miscalibrated its prompt.

Recommended scope for the review's writes:
- `state.md` (the cross-mode truth doc)
- `active/*.md` (in-progress items)
- A dropped-thread surfacing artifact (your choice — see §6)
- Append to a timeline / day log if you have one

Out of scope by default:
- Source code in any project
- Other agents' state files
- Configuration files
- Git commits

If the review wants to do something outside scope, it should surface a follow-up artifact instead of acting.

---

## 6. Dropped threads

The hardest case: the user mentioned X mid-session, the model said "got it, I'll come back to that," and never did. The session ends; X is invisible.

Review's job is to catch this. Walk the JSONL, find user messages whose actionable content was not addressed by the end of the session, and surface them.

How to surface:
- File an artifact (markdown doc, todo list entry, queue item) in a location the user actually checks
- Don't just append to a log nobody reads — that's burying, not surfacing

The artifact location is your call — your existing reminder/queue/inbox layer. JStack doesn't dictate this.

---

## 7. Decisions you make

1. **Trigger mechanism** — `Stop` hook, JSONL watcher, or both
2. **Spawn command** — how you invoke the review session (`claude --print`, OpenClaw-style router, custom wrapper)
3. **Review CLAUDE.md content** — your specific reconciliation procedure (what state files you trust, what thresholds for "stale", what your dropped-thread surfacing mechanism is)
4. **Recursion guard** — env var name (suggest `SKIP_SESSION_HOOK=1`)
5. **Review gate** — only review sessions newer than N hours, only sessions over M turns, etc. (avoid reviewing trivial pings)
6. **Failure mode** — what happens if the review session crashes, hits a tool error, or runs >K minutes (route to incident response, log silently, retry once)
7. **Owner identity** — does the agent review its own sessions, or does a dedicated reviewer agent review all sessions? Trade-off: own-review keeps context tight; central reviewer keeps procedures consistent.

---

## 8. What NOT to do

- **Don't have the review session edit source code.** Surface follow-up artifacts instead. The user (or a downstream session) makes code changes.
- **Don't let the review run unbounded.** Cap turn count or wall time. Reviews should be fast.
- **Don't review every session indiscriminately.** A 2-turn session probably has nothing to reconcile. Filter trivially-short sessions.
- **Don't bury the dropped-thread output.** If the output goes somewhere nobody reads, the system has failed.
- **Don't write the review procedure as a wall of text in CLAUDE.md.** Break it into discrete steps the review can execute. Walk-of-text procedures degrade into "model decides what to do."
- **Don't let the review fire on its own session-end.** Recursion guard is mandatory.

---

## 9. Minimum viable implementation

If you want this running ASAP:

1. Write `~/Agents/{Name}/review/CLAUDE.md` — the review's procedure. ≤ 100 lines.
2. Write a hook (Claude Code `Stop` hook or watcher script) that:
   - Checks for `SKIP_SESSION_HOOK=1`, exits if set
   - Extracts session ID from the trigger payload
   - Spawns: `SKIP_SESSION_HOOK=1 claude --print -p "review $SESSION_ID" --cwd ~/Agents/{Name}/review/`
3. Verify by running a session, ending it, watching the spawn happen, reading the spawned session's output
4. Add the dropped-thread surfacing mechanism once the reconciliation step is working

Each step independently testable.
