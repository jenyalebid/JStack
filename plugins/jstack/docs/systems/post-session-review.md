# Post-Session Review — Architecture & Configuration

Every agent session gets reviewed immediately after it ends: a purpose-spawned review session reconciles the agent's `state.md` and active items with what actually happened, extracts dropped threads into follow-ups, and logs timeline entries. The review's output is machine-validated — a review that doesn't show its evidence is rejected and re-spawned.

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
| Recent-activity check (today, or ≤4h) | Reviewing reopen-and-close of old sessions |
| Per-agent telegram debounce | One review per TG conversation, not per message |
| flock slots (`max_concurrent`, default 2) | Memory blowups from overlapping spawns |
| Timeline-grew validator | The model *claiming* `log_event` in prose while the command never executed |

## Configuration — `~/.claude/jstack/review.json` (env: `JSTACK_REVIEW_CONFIG`)

All keys optional; defaults are fully portable. Host-relevant keys:

| Key | Default | Use |
|-----|---------|-----|
| `agent_root` | `~/Agents` | Workspace root |
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

## Companion rule

`rules-stage/agent-state.md` — state.md discipline (review owns all writes; interactive sessions never write; ≤50 lines and ≤10 lines per entry; entries dated from when things happened).
