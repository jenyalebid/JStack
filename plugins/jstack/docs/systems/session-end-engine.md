# Session-End Engine — Architecture & Configuration

When an agent session ends, the engine writes that session's running memory. The `session_end_action` config picks how:

- **`selfwrite`** (default) — **resume a disposable duplicate of the session that just ended for ONE turn** so it writes its own seat-tagged timeline entry, then stop. It already lived the conversation, so it is the cheapest, best-informed writer. The transcript is dubbed (`bin/dub-session`), the dub is resumed for the write, then **deleted** — the primary session JSONL is never touched, so resuming the session later starts exactly where the user left it, with no trailing self-write turn in context or the resume picker. When the session was reviewed at a previous end (resumed, then ended again), the engine computes the last-reviewed boundary from the recorded offset and the prompt scopes the entry to **only the delta after it**. It does NOT extract threads, reconcile docs, or file follow-ups.
- **`review`** — the legacy fresh pass: a purpose-spawned fresh session re-ingests a transcript digest and runs the multi-phase review skill (walk the transcript, extract dropped threads into follow-ups, reconcile touched docs, log the timeline entry), machine-validated against required sections + evidence floors — rejected and re-spawned if it doesn't show its evidence. Still the right choice when you want the full stranger audit; also the manual `/…post-session-review` deep pass.
- **`off`** — do nothing on session end.

## Chain

```
SessionEnd hook (hooks/session-end-review.sh, or a host-wired equivalent)
  → bin/session-review-spawn <session_id> [transcript_path]   (detached)
    → gating: claim → agent resolution → loop/size/activity/TG guards → slot
    → session_end_action:
       selfwrite (default):
         dub-session {session_id} → {dub_id}      (disposable duplicate)
         claude --print --model {selfwrite_model} --resume {dub_id}
             -p "[SESSION-SELF-WRITE] … log one seat-tagged timeline entry
                 [+ resume-delta boundary when previously reviewed]"
         → delete the dub — the primary transcript is never touched
           (pid-stamped dub registry; stale dubs swept on every engine run)
       review (legacy):
         claude --print --model {model} from {agent_root}/{Name}/review/
             -p "[POST-SESSION-REVIEW]\n\n{skill_invocation} {session_id}"
         → validate output (required sections + evidence floors + timeline-grew)
         → retry once on rejection → escalate_cmd on persistent failure
```

The self-write turn uses `bin/log_event` (on the spawned PATH). The `review` skill (default `skills/post-session-review/SKILL.md`, `/jstack:post-session-review`) carries the multi-phase procedure; the engine is pure mechanism. Hosts point `skill_invocation` at their own skill and extend `required_sections` to match its output contract — the engine enforces whatever list it's given.

## Stack requirements (conventions assumed to exist)

1. **Agent workspaces** under `agent_root`, one `{Name}/` each. An agent is **reviewable iff `{agent_root}/{Name}/review/` exists** — that directory is also the spawn cwd, so walk-up loads the agent's identity + review glue.
2. **A review skill** resolvable by the spawned `claude` (plugin default or host-installed).
3. **`log_event`** for timeline writes — the engine prepends its own `bin/` to the spawned PATH, so the plugin's copy is always available.

## Gating (everything ported from two weeks of production hardening)

| Guard | What it prevents |
|-------|------------------|
| Atomic per-session claim (pid-stamped, stale-takeover) | Double review when host hook + plugin hook both fire |
| `SKIP_SESSION_HOOK=1` honored (set on the resume/spawn) + `[POST-SESSION-REVIEW]` marker check | Self-write-of-self-write and review-of-review loops. The self-write lands in a disposable dub, not the primary JSONL — nothing it appends can ever read as new user prose on a later reopen. |
| Filer-briefing skip | Burning a spawn on briefing-only resumed sessions closed without typing |
| `min_session_bytes` (1KB) | Reviewing empty sessions |
| reviewed-offset (state, per session) | Re-reviewing on resume-and-close: the transcript size is stamped at each spawn; a later SessionEnd with no new user prose past the stamp skips. Injected content (`<`-prefixed, `Caveat:`, isMeta) is not user prose. When new prose DID land, the offset also yields the last-reviewed boundary timestamp, injected so the write covers only the delta since the resume point. |
| Recent-activity check (today, or ≤4h) | Reviewing reopen-and-close of old sessions |
| Per-agent telegram debounce | One review per TG conversation, not per message |
| flock slots (`max_concurrent`, default 2) | Memory blowups from overlapping spawns |
| Auto-session skip (no typed prompt / TUI attach / TG) | Reviewing the high-frequency auto flood (cron/gateway/`--print` wakes) — their timeline line is written in-session by the Stop hook. **Carve-out:** sub-modes in `auto_review_submodes` (the purpose-built recurring crons) get the purpose-prompted engine self-write instead — a higher-grade seat entry + the dashboard stamp. |
| Timeline-grew validator | The model *claiming* `log_event` in prose while the command never executed |

## Configuration — `~/.claude/jstack/review.json` (env: `JSTACK_REVIEW_CONFIG`)

All keys optional; defaults are fully portable. Host-relevant keys:

| Key | Default | Use |
|-----|---------|-----|
| `agent_root` | `~/Agents` | Workspace root — agent resolution + seat resolution |
| `default_agent` | none | Owner of `$HOME`-cwd sessions |
| `project_dir_map` | `{}` | Encoded project dir → agent, for non-workspace sessions |
| `session_end_action` | `selfwrite` | `selfwrite` (dub the ended session, resume the dub 1 turn for one seat-tagged timeline entry, delete the dub) \| `review` (legacy fresh review spawn) \| `off` |
| `selfwrite_model` | `sonnet` | Model for the one-turn resume write |
| `selfwrite_max_turns` | `12` | Turn budget for the self-write |
| `selfwrite_timeout_secs` | `300` | Timeout for the self-write |
| `skill_invocation` | `/jstack:post-session-review` | Host playbook override (`review` action) |
| `required_sections` | core 5 | Extend to the host skill's output contract (`review` action) |
| `reviewed_submodes` | none (all) | Allowlist of user-session sub-modes to review, as `"agent/submode"` / `"*/submode"`. None = review every resolvable session |
| `auto_review_submodes` | none | Sub-modes (same match form) that get reviewed **even when auto** (no human drove them) — recurring crons that warrant the purpose-prompted self-write over the Stop-hook line. None/`[]` = nothing auto-reviewed |
| `timeline_inject` | none | `{"agent/submode": N, "*/submode": N}` — which seats get their last N timeline entries injected on SessionStart. Value `{"n": N, "interactive_only": true}` injects only sessions with a controlling terminal (human-driven), so headless wakes run lean. Unlisted seats get nothing |
| `model` / `max_turns` / `timeout_secs` / `max_attempts` | opus / 50 / 1200 / 2 | Spawn budget |
| `max_concurrent` / `slot_wait_secs` | 2 / 1800 | Concurrency |
| `telegram_cooldown_seconds` / `telegram_cooldown_file` | 300 / none | TG debounce; file form lets a host UI own the value |
| `tg_classify_cmd` | none | Host TG classifier (exit 0 = telegram session) |
| `escalate_cmd` | none (log only) | Called `<agent> <session_id> <reason>` after final failure |
| `extra_path` | `[]` | Host tool dirs prepended to the spawned PATH |
| `timeline_dir` | `~/Logs/Timeline` | Also exported as `JSTACK_TIMELINE_DIR` to spawns |
| `state_dir` | `~/.claude/jstack/review-state` | Claims, debounce markers, slots |
| `log_file` | `{state_dir}/session-review.log` | Pin to a host path if a dashboard parses it |

Log line contract (dashboards parse this): the self-write emits `YYYY-MM-DD HH:MM:SS SELFWRITE <sid8> → <agent>/<submode>` plus `SELFWRITE_DONE` / `SELFWRITE_FAIL` / `SELFWRITE_TIMEOUT`; the legacy review emits `SPAWN <sid8> → <agent> (...)` plus `DONE` / `INVALID` / `TIMEOUT` / `BLOCKED`.

## Kill switches & safety

- `JSTACK_REVIEW_DISABLED=1` — engine and hook exit immediately.
- The plugin SessionEnd hook is safe to ship alongside a host's own SessionEnd wiring: the claim makes spawning idempotent per session.
- On machines with no `agent_root` layout, every session resolves to no agent and the engine exits silently — installing the plugin never spawns surprise reviews.

## Timeline — the running memory

What a session *did* goes to the timeline as a seat-tagged entry (`log_event {agent}/{submode}`) — the thread the seat's next run reads on entry so it builds on prior runs instead of starting cold. The session-end self-write logs it (the `review` action does the same in its timeline phase); auto sessions log theirs in-session via the Stop hook. Store and views:

    log_event <agent[/submode]> "headline" [--at HH:MM] [--date YYYY-MM-DD] [--detail "..."]... [--session <sid>]
    log_event tail <agent[/submode]> [-n N] [--json]
    log_event verdict <agent[/submode]> shipped|drift|blocked|empty --note "..."

Storage is sqlite (`{timeline_dir}/timeline.db`, WAL — concurrent session-ends are safe) — the only artifact; reads and writes both go through `log_event`. Entries carry an `origin` (`direct` = a human drove the session, `indirect` = cron/gateway/spawned) resolved flag > `JSTACK_TIMELINE_ORIGIN` env > direct; the engine sets the env on its spawns (`indirect` for `auto_review_submodes` crons, `direct` otherwise) and the Stop hook's instructed command passes `--origin indirect`. `verdict` stamps an independent review's call on a seat's latest entry; it rides `tail`/injection. Stdlib only, no host dependency — portable to any machine running the plugin.

### The read half — SessionStart injection

Writing an entry is only half the loop: **a row in a db is not context in the session** — nothing reads it just because it exists. `hooks/session-start-inject.py` (a **SessionStart** hook) is the read half. On every new session it resolves the agent + sub-mode from cwd and injects the seat's last N timeline entries (via `log_event tail`) as `additionalContext`. Which seats, and how many entries, is the `timeline_inject` map in the review config — exact `"agent/submode"` keys win over `"*/submode"` wildcards; unlisted seats get nothing. So the write half (self-write / Stop hook) and the read half (this hook) together make the loop actually close.

Sub-mode resolution is identical on both sides of the loop (and in the Stop hook's source tag): the first path segment of cwd under `{agent_root}/{Name}`, or **`chat`** when cwd is the agent root. Cockpit sessions run at the agent root and are the `chat` seat by default — they do **not** cd into `chat/` (that would change the Claude Code project-dir key and orphan transcripts + memory). The `review` sub-mode is skipped. Recognized only for agents with a root CLAUDE.md; any other cwd → silent no-op. Kill switch: `JSTACK_TIMELINE_INJECT_DISABLED=1` (legacy `JSTACK_CONTINUITY_INJECT_DISABLED` honored). Defensive: any error → exit 0, never blocks a session.
