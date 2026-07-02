# Post-Session Review — Architecture & Configuration

Every agent session gets reviewed immediately after it ends: a purpose-spawned review session reconciles the agent's `active.md` and active items with what actually happened, extracts dropped threads into follow-ups, and logs timeline entries. The review's output is machine-validated — a review that doesn't show its evidence is rejected and re-spawned.

## Chain

```
SessionEnd hook (hooks/session-end-review.sh, or a host-wired equivalent)
  → bin/session-review-spawn <session_id> [transcript_path]   (detached)
    → gating: claim → agent resolution → loop/size/activity/TG guards → slot
    → claude --print --model {model} from {agent_root}/{Name}/review/
        -p "[POST-SESSION-REVIEW]\n\n{skill_invocation} {session_id}"
    → validate output (required sections + evidence floors + timeline-grew)
    → retry once on rejection → escalate_cmd on persistent failure
```

The skill (default `skills/post-session-review/SKILL.md`, `/jstack:post-session-review`) carries the review procedure; the engine is pure mechanism. Hosts with a richer playbook point `skill_invocation` at their own skill and extend `required_sections` to match its output contract — the engine enforces whatever list it's given.

## Stack requirements (conventions assumed to exist)

1. **Agent workspaces** under `agent_root`, one `{Name}/` each. An agent is **reviewable iff `{agent_root}/{Name}/review/` exists** — that directory is also the spawn cwd, so walk-up loads the agent's identity + review glue.
2. **A review skill** resolvable by the spawned `claude` (plugin default or host-installed).
3. **`log_event`** for timeline writes — the engine prepends its own `bin/` to the spawned PATH, so the plugin's copy is always available.

## Gating (everything ported from two weeks of production hardening)

| Guard | What it prevents |
|-------|------------------|
| Atomic per-session claim (pid-stamped, stale-takeover) | Double review when host hook + plugin hook both fire |
| `SKIP_SESSION_HOOK=1` honored + `[POST-SESSION-REVIEW]` marker check | Review-of-review loops |
| Filer-briefing skip | Burning a spawn on briefing-only resumed sessions closed without typing |
| `min_session_bytes` (1KB) | Reviewing empty sessions |
| reviewed-offset (state, per session) | Re-reviewing on resume-and-close: the transcript size is stamped at each spawn; a later SessionEnd with no new user prose past the stamp skips. Injected content (`<`-prefixed, `Caveat:`, isMeta) is not user prose. |
| Recent-activity check (today, or ≤4h) | Reviewing reopen-and-close of old sessions |
| Per-agent telegram debounce | One review per TG conversation, not per message |
| flock slots (`max_concurrent`, default 2) | Memory blowups from overlapping spawns |
| Timeline-grew validator | The model *claiming* `log_event` in prose while the command never executed |

## Configuration — `~/.claude/jstack/review.json` (env: `JSTACK_REVIEW_CONFIG`)

All keys optional; defaults are fully portable. Host-relevant keys:

| Key | Default | Use |
|-----|---------|-----|
| `agent_root` | `~/Agents` | Workspace root; also exported as `CONTINUITY_ROOT` to spawns |
| `default_agent` | none | Owner of `$HOME`-cwd sessions |
| `project_dir_map` | `{}` | Encoded project dir → agent, for non-workspace sessions |
| `skill_invocation` | `/jstack:post-session-review` | Host playbook override |
| `required_sections` | core 5 | Extend to the host skill's output contract |
| `model` / `max_turns` / `timeout_secs` / `max_attempts` | opus / 50 / 1200 / 2 | Spawn budget |
| `max_concurrent` / `slot_wait_secs` | 2 / 1800 | Concurrency |
| `telegram_cooldown_seconds` / `telegram_cooldown_file` | 300 / none | TG debounce; file form lets a host UI own the value |
| `tg_classify_cmd` | none | Host TG classifier (exit 0 = telegram session) |
| `escalate_cmd` | none (log only) | Called `<agent> <session_id> <reason>` after final failure |
| `extra_path` | `[]` | Host tool dirs prepended to the spawned PATH |
| `timeline_dir` | `~/Logs/Timeline` | Also exported as `JSTACK_TIMELINE_DIR` to spawns |
| `state_dir` | `~/.claude/jstack/review-state` | Claims, debounce markers, slots |
| `log_file` | `{state_dir}/session-review.log` | Pin to a host path if a dashboard parses it |

Log line contract (dashboards parse this): `YYYY-MM-DD HH:MM:SS SPAWN <sid8> → <agent> (...)` plus `DONE` / `INVALID` / `TIMEOUT` / `BLOCKED` lines.

## Kill switches & safety

- `JSTACK_REVIEW_DISABLED=1` — engine and hook exit immediately.
- The plugin SessionEnd hook is safe to ship alongside a host's own SessionEnd wiring: the claim makes spawning idempotent per session.
- On machines with no `agent_root` layout, every session resolves to no agent and the engine exits silently — installing the plugin never spawns surprise reviews.

## Continuity — the running memory

`active.md` is the **active-items index** (one line per open `active/{slug}.md`, nothing else). What a session *did* is not recorded there — it goes to the sub-mode's `continuity.md`, the thread the next run reads on entry so it builds on prior runs instead of starting cold. The review appends one plain-language line per session (Phase D of the skill) via the self-contained `bin/continuity` tool:

    continuity append  --agent <A> --mode <M> --summary "what this run did, a sentence or two"
    continuity verdict --agent <A> --mode <M> --verdict shipped|drift|blocked|empty --note "..."
    continuity show    --agent <A> --mode <M>

Storage is a JSON sidecar (`.continuity.json`) rendered one-way to `continuity.md` (never parsed back); compaction drops whole oldest entries at a hard cap, never truncates words. It resolves the agents tree from `CONTINUITY_ROOT` (the engine exports this from `agent_root`). Stdlib only, no host dependency — portable to any machine running the plugin.

### The read half — SessionStart injection

Writing `continuity.md` is only half the loop: **a file in the workspace is not context in the session** — nothing reads it just because it exists. `hooks/session-start-inject.py` (a **SessionStart** hook) is the read half. On every new session it resolves the agent + sub-mode from cwd and injects the sub-mode's `continuity.md` (what prior runs did) as `additionalContext`. So the write half (Phase D) and the read half (this hook) together make the loop actually close.

`active.md` is deliberately **not** injected — it's the active-items index, read as a file when needed; the running memory is what a cold start actually lacks. Sub-mode resolution is identical on both sides of the loop: the first path segment of cwd under `{agent_root}/{Name}`, or **`chat`** when cwd is the agent root. Cockpit sessions run at the agent root and are the `chat` mode by default — they do **not** cd into `chat/` (that would change the Claude Code project-dir key and orphan transcripts + memory); `chat` is only the folder its continuity is stored under (`{Name}/chat/continuity.md`). The `review` sub-mode is skipped. Recognized only for reviewable agents ({Name}/review/ exists); any other cwd → silent no-op. Kill switch: `JSTACK_CONTINUITY_INJECT_DISABLED=1`. Defensive: any error → exit 0, never blocks a session.

## Companion rule

`rules-stage/agent-active.md` — active.md discipline: it is the active-items index and nothing else. The review **verifies** it (each active line still valid) and never authors history into it; the running record lives in `continuity.md`.
