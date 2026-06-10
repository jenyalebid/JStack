---
name: post-session-review
description: Review the session that just ended — reconcile the agent's state.md and active items with what actually happened, extract dropped threads into follow-ups, and log timeline entries. Spawned by the jstack session-review engine; can also be invoked manually with a session id.
argument-hint: "<session-id>"
---

# /jstack:post-session-review — review the session that just ended

You are spawned in `{agent_root}/{Name}/review/`. Session ID is in `$ARGUMENTS`.

**You exist to do TWO things, and nothing else:**

1. **Self-consistency** — the next session reads truth. `state.md` and `active/*.md` must agree with reality. If they drift, the next session works on phantom inputs and re-surfaces ghosts.
2. **Thread extraction** — read the session JSONL. Topics the user raised that this session didn't resolve and aren't filed anywhere must be filed or explicitly dropped. **Judgment matters**: "forget it" / "skip" / "moving on" means drop. Raised-and-moved-on means file.

Your output is parsed by the engine. Missing required sections OR empty sections without per-item citation = rejected, re-spawned. Don't write "clean" or "none" without an evidence trail.

---

## Setup

```bash
SID="$ARGUMENTS"
AGENT_TITLE=$(basename "$(dirname "$PWD")")                              # Lynda, Jarvis, ...
AGENT=$(echo "$AGENT_TITLE" | tr '[:upper:]' '[:lower:]')                # lynda, jarvis, ...
JSONL=$(find ~/.claude/projects -name "${SID}.jsonl" -print -quit 2>/dev/null)
echo "session=$SID agent=$AGENT_TITLE jsonl=$JSONL"
```

If `$JSONL` is empty, emit a single-line `## SUMMARY` saying so and exit — the engine will surface it.

---

## Phase A — Thread extraction (FIRST)

Walk every user turn in `$JSONL`. Use `Read` for short sessions, `Bash` + `jq` (or python3) for long:

```bash
jq -r 'select(.type == "user") | .message.content
  | if type == "string" then . else map(select(.type == "text") | .text) | join(" ") end
  | gsub("\\s+"; " ")' "$JSONL" | head -200
```

**Skip injected events**: `<system-reminder>`, `<command-message>`, `<command-name>`, tool-result blobs, bootstrap payloads. Only count actual user prose.

For each distinct topic the user raised, classify into **exactly one** of:

- `resolved-in-session` — addressed before session ended; cite the resolution turn or artifact.
- `filed-elsewhere` — landed in `active/*.md`, a PR, a commit, a follow-up; cite destination.
- `user-dropped` — the user said skip / forget / moving on / actually-don't / later; cite the exact line.
- `unfinished-active-work` — the user was actively engaged on this topic in the last exchanges before session ended, work did NOT complete, no resolution reached.
- `silently-dropped` — raised mid-session, work moved on, never came back, not in any file.

For each `unfinished-active-work` or `silently-dropped` topic, file a follow-up:

```bash
file-followup "Glanceable issue title" "1–2 plain sentences: what's unfinished and why it matters."
```

(`file-followup` ships in the plugin's `bin/` — backend chosen by the plugin's `followup_backend` userConfig; with backend `none` it's a no-op, so ALSO record the thread in `state.md` so it isn't lost.)

Follow-up wording rules:
- **Title:** one short line, issue stated plainly — not "Approve X" / "Decide Y" action framing.
- **Body:** 1–2 plain sentences. No commit hashes, no GUIDs, no file paths, no hour estimates.
- **No duplicate filings.** If the same issue is already filed, update/skip — never stack a "still pending" copy.

If a topic is a correction or new rule the user gave, apply it at the most specific place that loads when the behavior matters (project CLAUDE.md, agent CLAUDE.md, a path-scoped rule, or memory) — never park corrections in `state.md`.

## Phase B — Accuracy

Reconcile docs in the agent workspace against what the session actually did:

```bash
cd "$(dirname "$PWD")"   # agent root
grep -rni "<phase-A-topic-keywords>" state.md active/*.md 2>/dev/null
```

For each match, classify and act:

- `agree` — doc and reality consistent — no action.
- `fossil` — doc references work that's done/superseded — **`Edit` the doc to remove/rewrite the line**.
- `phantom` — live work with no doc mention — **add the reference where it belongs** (usually `state.md`).
- `stale-active` — `active/*.md` untouched ≥ 7d — flag in DOC_RECONCILE; don't auto-prune.

Then update `state.md` (you are its only writer — see the `agent-state` rule):
- Remove done items; add new in-flight work with `[YYYY-MM-DD HH:MM]` stamps from when things actually happened (not now).
- Keep it ≤50 lines AND ≤10 lines per entry — detail belongs in `active/{slug}.md`, state.md carries the pointer.

## Phase C — Timeline

The day's spine lives at `$JSTACK_TIMELINE_DIR/$(date +%F).md` (default `~/Logs/Timeline/`). If this session produced something day-spine-worthy, it gets a `log_event` entry. Otherwise it doesn't.

**Read today's timeline first** — if your event is already covered by another block, don't duplicate; extend the existing block via `Edit` or skip. Format spec lives in the jstack `timeline.md` rule.

```bash
cat "${JSTACK_TIMELINE_DIR:-$HOME/Logs/Timeline}/$(date +%F).md" 2>/dev/null
log_event $AGENT --at HH:MM "headline ≤120 chars" --detail "≤80 chars" --detail "≤80 chars"
```

**Timeline-worthy:** code shipped, feature live, decision made, problem fixed, user directive that drove work, significant autonomous work.
**NOT timeline-worthy:** "reviewed session", "updated state.md", build counts, test counts, file paths, commit hashes, session UUIDs, internal cleanup.

`HH:MM` is **the timestamp of the LAST message in the reviewed conversation** in machine-local time. Not now. Session JSONL records UTC (`...Z` suffix) — convert before passing to `--at`. Sanity-check: the value must be ≤ current local time. If the session's last message is from a previous local day, pass `--date YYYY-MM-DD` too.

If nothing this session belongs, the `## TIMELINE` section says `none — {brief reason}`. Empty section without a reason = rejected.

---

## Required output (exact section headers — the engine parses by name)

```
## TRANSCRIPT_WALK
- turn 1 [HH:MM]: "{first 60 chars of user message}" → {classification} → {citation OR disposition}
- turn 2 [HH:MM]: ...
(every distinct user turn. **If there were none, the FIRST line of this section MUST start with the literal phrase `no user turns` — verbatim, lowercase. Example: `no user turns — automation-triggered session (skill payload only)`.**)

## DOC_RECONCILE
- {file:line} — {fossil/phantom/stale-active} — {action taken or flag}
OR
- clean — examined: state.md ({N} topic matches), active/ ({K} files); all consistent.

## ACTIONS_TAKEN
- Edit {path:line} — {what changed}
- file-followup "{title}" "{body}"
- ...
OR
- none — {N} user turns walked, {K} docs grepped; no action because:
  - {topic 1}: {per-topic reasoning}

## TIMELINE
- log_event {agent} --at HH:MM "headline" [--detail "..." --detail "..."]
OR
- none — {brief reason: routine maintenance / already covered by {agent} block at HH:MM / no day-spine-worthy event}

## SUMMARY
One sentence: most important thing about this session (or the biggest miss).
```

---

## Rules

- **One pass.** Don't fork, don't sub-spawn.
- **Read the JSONL once** at Phase A start. Don't re-walk it for Phase B.
- **Output structured sections verbatim** — exact headers, in order.
- **Agent-specific glue** in `{agent_root}/{Name}/review/CLAUDE.md` (walk-up loaded) applies after this skill's procedure — read it.
