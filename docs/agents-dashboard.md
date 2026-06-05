# Agents Dashboard — Build Spec

A local FastAPI dashboard for browsing every Claude Code agent on the machine: their sub-Claudes, their chat history, with tagging and categorization.

Scope: **Agents** surface only. Two pages — **Team** (one card per agent) and **All Chats** (every session, filtered/searched). An inner agent page lists that agent's sub-modes and history.

This doc describes the pattern. You define your own agent roster, your own sub-mode names, your own categories.

---

## 1. Directory pattern

Every agent lives under one root dir. Reference shape (names are illustrative — you pick):

```
~/Agents/
  {AgentName}/
    CLAUDE.md            # identity — auto-loaded on any session in this tree
    state.md             # (optional) cross-mode state file
    active/              # (optional) in-progress items
    {sub-mode}/          # any subdir that ISN'T a reserved name = a sub-mode
      CLAUDE.md          # sub-mode playbook (walk-up appends to root)
      state.md           # (optional)
    {sub-mode}/{nested}/ # nested sub-modes are allowed
```

**Sub-modes** are subdirectories of an agent root. They represent the same agent operating in a different context (interactive CLI, scheduled job, inbound chat, etc.) — not separate agents. Claude Code's native walk-up means a session inside a sub-mode dir loads the root `CLAUDE.md` then the sub-mode `CLAUDE.md`.

You decide what's reserved (non-sub-mode) for your setup. Typical reservations: hidden dirs (`.claude`, `.git`), data dirs you don't want surfaced as sub-modes (`memory`, `active`).

You may want a special class of sub-mode for long-horizon work — give it a fixed parent dir (`missions/`, `projects/`, `goals/` — your call) so it can be discovered and rendered differently in the UI.

---

## 2. Agent registry

Single config file. One source of truth for which agents exist, where their workspaces live, and how to render them.

Suggested shape:

```json
{
  "_roles": {
    "_comment": "Role enum — drives badge colors and any role-specific behavior",
    "role-a": "What role A does",
    "role-b": "What role B does"
  },
  "{agent_id}": {
    "active": true,
    "workspace": "~/Agents/{Name}",
    "roles": ["role-a"],
    "description": "One line",
    "emoji": "🔧"
  }
}
```

Required per agent: `active`, `workspace`, `roles`. Optional: `description`, `emoji`, anything else your UI needs.

Keys starting with `_` are reserved for comments/enums and skipped by the loader.

If you want sub-modes and special-class sub-modes (missions, projects, whatever) discoverable from config rather than only from disk scan, extend the schema:

```json
"{agent_id}": {
  ...
  "submodes": ["chat", "scheduled", "inbound"],
  "missions": ["slug-a", "slug-b"]
}
```

Or just discover them by scanning subdirs of `workspace` and excluding reserved names. Either works — pick one and stick to it.

---

## 3. Registry helper module

Build one Python module that owns all path resolution. Every other piece of dashboard code calls into here — no direct workspace path construction anywhere else.

Functions:

| Function | Returns | Purpose |
|---|---|---|
| `load_raw()` | `dict` | Read config, cache by mtime |
| `all_agents(include_inactive=False)` | `{id: cfg}` | Skip `_*` keys |
| `active_agents()` | `{id: cfg}` | active=true only |
| `split_id(agent_id)` | `(base, sub_path \| None)` | Parse a sub-mode id into base + relative sub-path |
| `workspace(agent_id)` | `Path` | Resolve any id (base or sub-mode) to its dir |
| `is_umbrella(agent_id)` | `bool` | True if any sub-mode subdir exists under this agent |
| `is_umbrella_root(path)` | `bool` | True if path is an agent root |
| `submode_ids(base)` | `list[str]` | Every sub-mode id under this base |
| `project_dir_to_agent(dirname)` | `(base, sub_path) \| None` | Reverse-lookup from Claude project-dir name |

**Sub-mode id convention** (suggested): `{base}-{sub_path_with_dashes}`. So `agent-chat` resolves to `{workspace}/chat/`, `agent-chat-inbound` resolves to `{workspace}/chat/inbound/`. `split_id` tries each possible split point left-to-right and picks the first one where the base is in the registry AND the resulting subdir exists.

This is one convention; others work. Whatever you pick, encode it in this module so the rest of the code is convention-free.

---

## 4. Session → agent mapping

Claude Code stores every session as a JSONL file at:

```
~/.claude/projects/{project-key}/{session-uuid}.jsonl
```

`project-key` is the session's working directory encoded as:
- Replace `/` with `-`
- Drop the leading `-` (actually it stays — the encoded path starts with `-`)
- Periods in path components also become `-`

Example: cwd `/Users/me/Agents/Foo/chat` → project-key `-Users-me-Agents-Foo-chat`.

**To list sessions for an agent:**
1. Compute project-key from the agent's workspace path.
2. Scan `~/.claude/projects/{project-key}/*.jsonl`.
3. If the agent has sub-modes, repeat for each sub-mode workspace.
4. Sort by file mtime.

**Project-key resolver:**

```python
def workspace_to_project_key(ws_path: str) -> str:
    simple = ws_path.replace("/", "-").lstrip("-")
    if (CLAUDE_PROJECTS / simple).exists():
        return simple
    normalized = ws_path.lstrip("/").replace("/", "-").replace(".", "-")
    for d in CLAUDE_PROJECTS.iterdir():
        if d.is_dir() and d.name.lstrip("-").replace(".", "-") == normalized:
            return d.name
    return simple
```

**JSONL parsing** — newline-delimited JSON, skip lines that don't parse. Fields the dashboard cares about:
- `type`: `"user"` | `"assistant"` | `"summary"` | `"system"`
- `message.content`: string or list of blocks
- `message.usage.input_tokens` / `output_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens`
- `cwd`, `sessionId` (session metadata lines)
- `gitBranch`, `userType`

Extract once per session, cache in memory keyed by `(file_path, mtime)`. Re-parse only when mtime changes.

---

## 5. Session classification

Every session gets exactly one category. **You define the categories that match your operational surfaces** — there's no canonical list. Common axes to think about:

- **Who triggered it** — operator-interactive vs. automatic (cron, daemon, webhook)
- **What surface** — terminal CLI, chat platform, scheduled job, incident trigger
- **What context** — base agent identity vs. specific sub-mode (project work vs. reminder handling vs. inbound message)

Whatever categories you land on, classification follows the same lookup order. First match wins:

1. **Manual override** — `{session_id: category}` from a metadata file. Operator can pin a session via UI.
2. **Spawn-time role tag** — if a daemon spawns sessions programmatically, have it record the role somewhere queryable (filesystem symlink, sidecar JSON, database row). Look it up here.
3. **Directory mapping** — the sub-mode dir name maps to a category. You define this table:
   ```python
   DIR_TO_CATEGORY = {
       "chat": "operator-cli",
       "inbound": "chat-platform",
       "scheduled": "automatic",
       # ... your sub-modes → your categories
   }
   ```
   Some sub-modes host BOTH operator and automatic sessions (e.g. you can `cd` in for an interactive session OR cron can fire one). Split them using the JSONL's `entrypoint` field: `sdk-cli` = `claude --print` (programmatic), otherwise TTY = interactive.
4. **Custom session name pattern** — if your spawner sets a `--name`, you can pattern-match it here for finer routing.
5. **Fallback** — pick a sensible default category for sessions that don't match any rule.

**Override storage** — one JSON file, all session metadata in one place:

```json
{
  "{session_id}": {
    "label": "Manual rename",
    "category_override": "operator-cli",
    "reviews": {
      "{reviewer_id}": {"reviewed_at": 1717532400.0}
    }
  }
}
```

Labels, category overrides, and review stamps share the file. Don't split.

---

## 6. Tagging (labels)

Auto-derive a display label from session content, priority order:
1. Custom session title (set by spawner via `--name`)
2. Deterministic trigger prefix (e.g. session-start markers your spawner inserts) — strip the prefix
3. AI-generated summary (Claude Code writes a `type: "summary"` line)
4. Last user prompt (truncated; skip system/notification lines)
5. First user message (truncated)
6. Slug derived from project-key

**Manual label** overrides everything. UI exposes an editable name field per session row; `PUT /api/conversations/{session_id}/label` writes to the metadata file. Empty value clears the override.

---

## 7. Review stamps

If your setup runs reviews on sessions (post-session and/or scheduled deep-reviews), give each reviewer an id and stamp:

```json
"reviews": {
  "{reviewer_id}": {"reviewed_at": <unix_ts>}
}
```

Per-stamp state for UI:
- `unreviewed` — no stamp
- `reviewed` — stamped, `reviewed_at >= session.mtime`
- `stale` — stamped, but `session.mtime > reviewed_at` (session continued after review)

Combine multiple review tracks into a `review_state`: `none` / `partial` / `all`. Use it for card border accent.

Skip this section entirely if you don't review sessions.

---

## 8. HTTP API

Read-only unless noted. Gate behind whatever auth your dashboard uses (or none for local-only).

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/agents` | `{agents: [...]}` — one entry per active agent |
| `GET` | `/api/agents/sessions?path={ws_path}&agent_id={id}` | `{sessions: [...]}` — fans out across sub-modes if path is an agent root |
| `GET` | `/api/agents/{base}/submodes` | `{base, submodes: [...]}` |
| `GET` | `/api/conversations` | All sessions across the machine, classified |
| `PUT` | `/api/conversations/{session_id}/label` | Body `{label}` — manual rename |
| `POST` | `/api/conversations/delete` | Body `{session_ids: [...]}` |
| `POST` | `/api/conversations/delete-empty` | Sessions with no real user messages |
| `POST` | `/api/conversations/delete-older-than` | Body `{age: "day"\|"week"\|"month"\|"all"}` |
| `GET` | `/api/agents/{id}/file?name={filename}` | Raw content for the side viewer (CLAUDE.md, state.md, etc.) |
| `POST` | `/api/workspace-chat` | Body `{path, resume?}` — opens a chat (§11) |

**Agent object:**

```json
{
  "agent_id": "...",
  "agent_name": "...",
  "emoji": "🔧",
  "role": "...",
  "description": "...",
  "path": "/abs/workspace/path",
  "files": ["CLAUDE.md", "state.md"],
  "chat_count": 42,
  "type_counts": {"category-a": 10, "category-b": 32},
  "active": true
}
```

**Session object:**

```json
{
  "session_id": "uuid",
  "file_path": "/abs/path/to/session.jsonl",
  "label": "rendered or custom",
  "preview": "first user msg (truncated)",
  "last_msg": "last assistant msg (truncated)",
  "mtime": "2026-06-04T10:30:00",
  "mtime_display": "Jun 04, 10:30",
  "in_tokens": 1234,
  "out_tokens": 567,
  "total_tokens": 1801,
  "last_context": 45000,
  "calls": 12,
  "chat_type": "category-a",
  "review": {"review_state": "partial"},
  "agent_base": "foo",
  "sub_mode": "chat"
}
```

**Sub-mode object:**

```json
{
  "id": "foo-chat",
  "name": "chat",
  "kind": "submode",
  "path": "/abs/path",
  "has_claude_md": true,
  "files": ["CLAUDE.md", "state.md"],
  "chat_count": 12,
  "type_counts": {...}
}
```

`kind` differentiates regular sub-modes from your special class (missions/projects/whatever) so the UI can style them differently.

---

## 9. Pages

### `/agents` — Team grid

One card per active agent.

Card content:
- Emoji + agent name (large)
- Agent id (mono, small)
- Role badge (colored by role)
- Description (one line)
- File chips for notable root-level files — clickable, open in side panel
- Type-count pills: one per non-zero category, colored to match
- Actions: **Open** (→ `/agents/{id}`) and **New Chat** (→ `POST /api/workspace-chat`)

Grid: `grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px`.

Top bar: tabs **Team** | **All Chats**.

### `/agents/{name}` — Inner agent page

Header: emoji + name + role + description.

**Section A — Sub-modes**: grid of cards. Each card shows sub-mode name, kind badge, per-category count pills, action buttons (open chat, view CLAUDE.md). Order regular sub-modes first, special class (missions etc.) last.

**Section B — Chat history**: full session list for this agent across all sub-modes. Sortable by date or grouped by sub-mode. Per-row: label (editable), mtime, sub-mode tag, category pill, token totals, review state, actions menu (rename, resume, delete).

### `/conversations` — All Chats

Three top-level tabs you define around your category groupings. A reasonable split:
- **All** — everything
- **Direct** — operator-interactive categories
- **Auto** — programmatically-spawned categories

Sub-tabs under each parent filter by individual category.

Toolbar: search box (filters label + preview + last_msg, case-insensitive), bulk-delete dropdown (older than day/week/month, all, empty).

Per-row: agent emoji + name, sub-mode tag, category pill, label (editable), mtime, token totals, review state, actions menu (rename, resume, delete, override category).

---

## 10. UI primitives

Dark theme. CSS variables:

```
--bg, --bg2, --bg3        backgrounds (darkest → mid)
--text, --text2, --text3  text (brightest → mid-grey)
--border                  subtle border
--accent                  primary green
--accent2                 primary blue
--warn                    amber
--danger                  red
--radius                  8px
```

Pick one color per category for pills/borders/dots. Suggested hues: blue, purple, amber, magenta, yellow, green, red — enough distinct for ~7 categories without collision. Apply the same rule to role badges (one color per role).

Pill style: `font-size: 0.68rem; padding: 2px 8px; border-radius: 4px; font-family: 'SF Mono', monospace`. Use a tinted background (`rgba(..., 0.1)`) + matching text color.

Card hover state: border color shifts to `--accent2`.

Review dots: small filled circles. Green = reviewed, amber = stale, hollow = unreviewed.

---

## 11. Chat launch

The action buttons need to open a Claude Code session in a terminal. Platform-specific — the spec is the contract; you build the local mechanism.

Contract: `POST /api/workspace-chat` with body `{path: "<workspace cwd>", resume?: "<session_id>"}`.

Two delivery modes:

**Local** — dashboard runs on the same machine as the operator. Server-side: open a new terminal window at `path`, run `claude` (append `--resume <session_id>` if provided). On macOS: AppleScript drives Terminal.app or iTerm2. On Linux: `gnome-terminal --working-directory=... -- claude`. On Windows: equivalent via PowerShell.

**Remote** — dashboard viewed in a browser on a different machine. Server returns `{ok: true, mode: "remote", cwd, session_id}`. Frontend opens a custom URL scheme registered on the operator's machine that does the local terminal-open. Operator's machine handles it.

Differentiate via a request flag (query param or header) — frontend sets it when it knows it's viewed remotely.

---

## 12. Decisions you make

Things the spec deliberately leaves open — your operational context dictates:

1. **Your agent roster** — who exists, what they do, what their roles are.
2. **Your sub-mode names** — `chat`, `inbound`, `scheduled`, whatever fits.
3. **Your reserved subdir names** — what dirs under an agent root are NOT sub-modes (hidden, data, in-progress folders).
4. **Your special sub-mode class** — if you want long-horizon work (missions/projects/goals) rendered differently. Optional.
5. **Your categories** — the list of `chat_type` values + the directory→category mapping table.
6. **Your color palette** — role badge colors, category pill colors. Pick once, apply everywhere.
7. **Daemon spawn tagging** — if you have a daemon that spawns sessions, how does it record the role so classification can find it (symlink, sidecar JSON, DB row)? If you have no such daemon, skip step 2 of classification entirely.
8. **Terminal launch implementation** — your OS, your terminal app.
9. **Auth** — local-only = none; otherwise plug in whatever you use.
10. **Whether to wire reviews** — §7 is optional. Skip cleanly if you don't run reviews on sessions.

---

## 13. Build order

For fastest path to a working dashboard:

1. Registry config + helper module (§2, §3)
2. Session JSONL parser + project-key resolver (§4)
3. Classification (§5) — start with directory-only, no daemon tagging
4. `/api/agents` + `/api/agents/sessions` endpoints
5. `/agents` Team page (§9, §10)
6. Session metadata file + label endpoint (§6)
7. `/conversations` All Chats page with search + bulk delete
8. Sub-modes endpoint + inner agent page
9. Review stamps + dots (§7) — skip if not applicable
10. Chat launch (§11) — last; sessions resume from CLI manually until wired

Each step is independently runnable and verifiable.
