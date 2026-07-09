# Session-End Engine — Architecture & Configuration

When an agent session ends, the engine writes that session's running memory. The `session_end_action` config picks how:

- **`selfwrite`** (default) — **resume the session that just ended for ONE turn** so it writes its own timeline line + continuity, then stop. It already lived the conversation, so it is the cheapest, best-informed writer; the write **appends to the same session JSONL** (no separate review conversation). It does NOT extract threads, reconcile docs, or file follow-ups.
- **`review`** — the legacy fresh pass: a purpose-spawned `review/` session re-ingests a transcript digest and runs the multi-phase review skill (reconcile `active.md` + active items, extract dropped threads into follow-ups, log timeline), machine-validated against required sections + evidence floors — rejected and re-spawned if it doesn't show its evidence. Still the right choice when you want the full stranger audit; also the manual `/…post-session-review` deep pass.
- **`off`** — do nothing on session end.

## Chain

```
SessionEnd hook (hooks/session-end-review.sh, or a host-wired equivalent)
  → bin/session-review-spawn <session_id> [transcript_path]   (detached)
    → gating: claim → agent resolution → loop/size/activity/TG guards → slot
    → session_end_action:
       selfwrite (default):
         claude --print --model {selfwrite_model} --resume {session_id}
             -p "[SESSION-SELF-WRITE] … log one timeline line + reconcile continuity"
         → re-record reviewed offset past the appended turn (no reopen re-fire)
       review (legacy):
         claude --print --model {model} from {agent_root}/{Name}/review/
             -p "[POST-SESSION-REVIEW]\n\n{skill_invocation} {session_id}"
         → validate output (required sections + evidence floors + timeline-grew)
         → retry once on rejection → escalate_cmd on persistent failure
```

The self-write turn uses `bin/log_event` + `bin/continuity` (both on the spawned PATH). The `review` skill (default `skills/post-session-review/SKILL.md`, `/jstack:post-session-review`) carries the multi-phase procedure; the engine is pure mechanism. Hosts point `skill_invocation` at their own skill and extend `required_sections` to match its output contract — the engine enforces whatever list it's given.

## Stack requirements (conventions assumed to exist)

1. **Agent workspaces** under `agent_root`, one `{Name}/` each. An agent is **reviewable iff `{agent_root}/{Name}/review/` exists** — that directory is also the spawn cwd, so walk-up loads the agent's identity + review glue.
2. **A review skill** resolvable by the spawned `claude` (plugin default or host-installed).
3. **`log_event`** for timeline writes — the engine prepends its own `bin/` to the spawned PATH, so the plugin's copy is always available.

## Gating (everything ported from two weeks of production hardening)

| Guard | What it prevents |
|-------|------------------|
| Atomic per-session claim (pid-stamped, stale-takeover) | Double review when host hook + plugin hook both fire |
| `SKIP_SESSION_HOOK=1` honored (set on the resume/spawn) + `[POST-SESSION-REVIEW]` marker check | Self-write-of-self-write and review-of-review loops. The self-write also re-records the reviewed offset past its own appended turn, so a later reopen sees no new user prose and skips. |
| Filer-briefing skip | Burning a spawn on briefing-only resumed sessions closed without typing |
| `min_session_bytes` (1KB) | Reviewing empty sessions |
| reviewed-offset (state, per session) | Re-reviewing on resume-and-close: the transcript size is stamped at each spawn; a later SessionEnd with no new user prose past the stamp skips. Injected content (`<`-prefixed, `Caveat:`, isMeta) is not user prose. |
| Recent-activity check (today, or ≤4h) | Reviewing reopen-and-close of old sessions |
| Per-agent telegram debounce | One review per TG conversation, not per message |
| flock slots (`max_concurrent`, default 2) | Memory blowups from overlapping spawns |
| Auto-session skip (no typed prompt / TUI attach / TG) | Reviewing the high-frequency auto flood (cron/gateway/`--print` wakes) — their timeline line is written in-session by the Stop hook. **Carve-out:** sub-modes in `auto_review_submodes` (the purpose-built recurring crons whose `continuity.md` is load-bearing) ARE still reviewed even when auto — the review is the only writer of their continuity, so skipping them silently freezes it. |
| Timeline-grew validator | The model *claiming* `log_event` in prose while the command never executed |

## Configuration — `~/.claude/jstack/review.json` (env: `JSTACK_REVIEW_CONFIG`)

All keys optional; defaults are fully portable. Host-relevant keys:

| Key | Default | Use |
|-----|---------|-----|
| `agent_root` | `~/Agents` | Workspace root; also exported as `CONTINUITY_ROOT` to spawns |
| `default_agent` | none | Owner of `$HOME`-cwd sessions |
| `project_dir_map` | `{}` | Encoded project dir → agent, for non-workspace sessions |
| `session_end_action` | `selfwrite` | `selfwrite` (resume the ended session, 1 turn, timeline + continuity) \| `review` (legacy fresh `review/` spawn) \| `off` |
| `selfwrite_model` | `sonnet` | Model for the one-turn resume write |
| `selfwrite_max_turns` | `12` | Turn budget for the self-write |
| `selfwrite_timeout_secs` | `300` | Timeout for the self-write |
| `skill_invocation` | `/jstack:post-session-review` | Host playbook override (`review` action) |
| `required_sections` | core 5 | Extend to the host skill's output contract (`review` action) |
| `reviewed_submodes` | none (all) | Allowlist of user-session sub-modes to review, as `"agent/submode"` / `"*/submode"`. None = review every resolvable session |
| `auto_review_submodes` | none | Sub-modes (same match form) that get reviewed **even when auto** (no human drove them) — the recurring crons whose `continuity.md` is running memory the next run boots on. None/`[]` = nothing auto-reviewed |
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

## Continuity — the running memory

`active.md` is the **active-items index** (one line per open `active/{slug}.md`, nothing else). What a session *did* is not recorded there — it goes to the sub-mode's `continuity.md`, the thread the next run reads on entry so it builds on prior runs instead of starting cold. The session-end self-write reconciles the STANDING and appends one plain-language line per session (the `review` action does the same in Phase D of the skill) via the self-contained `bin/continuity` tool:

    continuity append  --agent <A> --mode <M> --summary "what this run did, a sentence or two"
    continuity verdict --agent <A> --mode <M> --verdict shipped|drift|blocked|empty --note "..."
    continuity show    --agent <A> --mode <M>

Storage is a JSON sidecar (`.continuity.json`) rendered one-way to `continuity.md` (never parsed back); compaction drops whole oldest entries at a hard cap, never truncates words. It resolves the agents tree from `CONTINUITY_ROOT` (the engine exports this from `agent_root`). Stdlib only, no host dependency — portable to any machine running the plugin.

### The read half — SessionStart injection

Writing `continuity.md` is only half the loop: **a file in the workspace is not context in the session** — nothing reads it just because it exists. `hooks/session-start-inject.py` (a **SessionStart** hook) is the read half. On every new session it resolves the agent + sub-mode from cwd and injects the sub-mode's `continuity.md` (what prior runs did) as `additionalContext`. So the write half (Phase D) and the read half (this hook) together make the loop actually close.

`active.md` is deliberately **not** injected — it's the active-items index, read as a file when needed; the running memory is what a cold start actually lacks. Sub-mode resolution is identical on both sides of the loop: the first path segment of cwd under `{agent_root}/{Name}`, or **`chat`** when cwd is the agent root. Cockpit sessions run at the agent root and are the `chat` mode by default — they do **not** cd into `chat/` (that would change the Claude Code project-dir key and orphan transcripts + memory); `chat` is only the folder its continuity is stored under (`{Name}/chat/continuity.md`). The `review` sub-mode is skipped. Recognized only for reviewable agents ({Name}/review/ exists); any other cwd → silent no-op. Kill switch: `JSTACK_CONTINUITY_INJECT_DISABLED=1`. Defensive: any error → exit 0, never blocks a session.

## Companion rule

`rules-stage/agent-active.md` — active.md discipline: it is the active-items index and nothing else. The `review` action **verifies** it (each active line still valid) and never authors history into it; the self-write leaves it alone. The running record lives in `continuity.md`.
