---
name: day-audit
description: Reverify a day's shipped work across every repo — did the day's commits, especially bug fixes, actually improve each app without regressing something else or sneaking in something big. Each repo is audited by its OWNING agent (from the agent registry) so the review carries real domain context, not a cold-start guess. Use when the user wants a day reviewed ("day audit", "audit yesterday", "did anything we shipped break"); ties into the timeline as the claims to check against. Takes an optional date (today | yesterday | "june 01" | YYYY-MM-DD); defaults to today.
argument-hint: "[today|yesterday|<date>]"
---

# /jstack:day-audit — reverify a day's shipped work, by the agents who own it

The timeline is the day's spine — what each agent *says* it shipped, fixed, decided. This skill treats that spine as a **claims document** and checks it against the **actual commits** in every repo: did the day's work — especially the bug fixes — make each app better, or did a fix regress another issue, break a consumer, or smuggle in something big?

You don't audit every repo yourself. You **dispatch each repo's audit to the agent that owns it** (per the agent registry), so the review runs with that codebase's domain context — what a regression actually looks like there, the real blast radius — instead of a generic auditor reconstructing the repo from the diff. You are the initiator: discover, fan out, synthesize. Report-only on code; the only write is one timeline block.

Believe nothing in the timeline — it tells you where to look, never what's true. Verify from diffs.

---

## Step 0 — Resolve the day

`$ARGUMENTS` is an optional date token. Normalize it to `YYYY-MM-DD` (machine-local):

```bash
DAY=$(python3 - "$ARGUMENTS" <<'PY'
import sys, datetime
raw = " ".join(sys.argv[1:]).strip().lower()
today = datetime.date.today()
if raw in ("", "today"):        print(today); sys.exit()
if raw == "yesterday":          print(today - datetime.timedelta(days=1)); sys.exit()
for fmt in ("%Y-%m-%d", "%m-%d", "%m/%d", "%B %d", "%b %d", "%B %d %Y", "%b %d %Y", "%d %B", "%d %b"):
    try:
        d = datetime.datetime.strptime(raw, fmt).date()
        if "%Y" not in fmt: d = d.replace(year=today.year)
        print(d); sys.exit()
    except ValueError: pass
print("UNPARSEABLE", file=sys.stderr); sys.exit(1)
PY
)
[ -z "$DAY" ] && { echo "Couldn't parse date '$ARGUMENTS' — pass today, yesterday, a month-day, or YYYY-MM-DD."; exit 1; }
NOW=$(date +%H:%M)
echo "auditing $DAY (logging at $NOW)"
```

If it can't parse, ask the user for the date and stop.

## Step 1 — Load the day's claims (the timeline)

```bash
TLDIR="${JSTACK_TIMELINE_DIR:-$HOME/Logs/Timeline}"
cat "$TLDIR/$DAY.md" 2>/dev/null || echo "(no timeline for $DAY)"
```

Read every block. The claims that matter most are the **fixes and ships** ("fixed X, shipped to develop", "issue #NNN"). Keep the full file — each repo auditor gets it as grounding, and you use it in synthesis to catch claim↔commit gaps. An empty timeline is fine: the audit then runs purely off commits.

## Step 2 — Resolve repos and their owning agents

Repos are discovered under the portable code root (`repo_root`, else parent of `agent_root`). Ownership comes from the **agent registry** (`agent_registry`, else `{agent_root}/agents.json`) — each agent's entry declares its `workspace` and the `repos` it owns. **No hardcoded per-machine paths, no Alpine specifics.** This resolver prints one line per repo — `agent⇥workspace⇥repo_path` (`-` agent = unowned):

```bash
AGENT_ROOT="${user_config.agent_root}"; AGENT_ROOT="${AGENT_ROOT/#\~/$HOME}"
REPO_ROOT="${user_config.repo_root}"; [ -z "$REPO_ROOT" ] && REPO_ROOT="$(dirname "$AGENT_ROOT")"; REPO_ROOT="${REPO_ROOT/#\~/$HOME}"
REGISTRY="${user_config.agent_registry}"; [ -z "$REGISTRY" ] && REGISTRY="$AGENT_ROOT/agents.json"; REGISTRY="${REGISTRY/#\~/$HOME}"

python3 - "$AGENT_ROOT" "$REPO_ROOT" "$REGISTRY" <<'PY'
import json, os, subprocess, sys, glob
agent_root, repo_root, registry = sys.argv[1:4]
def norm(s): return os.path.basename(s.rstrip("/")).lower().replace("_", "-")  # WBIS_iOS == WBIS-iOS
repos = sorted({os.path.dirname(g) for g in glob.glob(os.path.join(repo_root, "*", ".git"))})
owners = {}
try:
    for key, a in json.load(open(registry)).items():
        if isinstance(a, dict):
            for r in (a.get("repos") or []): owners[norm(r)] = (key, a.get("workspace", ""))
except (FileNotFoundError, ValueError): pass
def origin(r):
    try:
        u = subprocess.run(["git","-C",r,"remote","get-url","origin"], capture_output=True, text=True).stdout.strip()
        return norm(u[:-4] if u.endswith(".git") else u)
    except Exception: return ""
for repo in repos:
    hit = next((owners[k] for k in (norm(repo), origin(repo)) if k in owners), ("-", ""))
    print(f"{hit[0]}\t{hit[1]}\t{repo}")
PY
```

If no repos print, tell the user the root resolved to `$REPO_ROOT` and nothing under it is a git repo (they likely need to set `repo_root`), then stop. An unowned repo (`-`) is fine — it just gets a generic auditor in Step 4.

## Step 3 — Pull each repo's commits for the day

For every repo `R` from Step 2, collect the commits whose **commit date** lands on `$DAY`, across all refs (work lands on `develop` / feature branches / pushed remotes, not just `main`):

```bash
git -C "$R" log --all --no-merges \
  --since="${DAY}T00:00:00" --until="${DAY}T23:59:59" \
  --date=local --pretty=format:'%h %an %s' 2>/dev/null
```

Drop repos with no commits. If **every** repo is empty, skip to Step 6 and log the one-line "no commits" block.

## Step 4 — Fan out one auditor per repo, under its owning agent

For each repo with commits, **dispatch a `general-purpose` agent via the Agent tool, all in parallel** (one message, multiple tool calls). The owning agent doesn't run as a separate identity here — you deliver its context by telling the auditor to **read that agent's role file and the repo's own `CLAUDE.md` first**, then audit. Unowned repo (`-`): skip the role-file line; the auditor still reads the repo's `CLAUDE.md`.

Kickoff prompt (fill `{agent}`, `{workspace}`, `{R}`, `{DAY}`, timeline):

> You are a regression auditor reviewing **{agent}**'s repo `{R}` — but you did NOT write this code and have no stake in it being right; your job is to find what the day's commits broke. **First load domain context:** read `{workspace}/CLAUDE.md` (the owning agent's role + where this codebase's detail and gotchas live) and `{R}/CLAUDE.md` if present. Then audit ONLY the commits made on **{DAY}**:
> `git -C {R} log --all --no-merges --since="{DAY}T00:00:00" --until="{DAY}T23:59:59" --date=local --pretty=oneline`, reading each with `git -C {R} show <sha>`.
> Below is the day's TIMELINE — the team's claims; believe none of it, use it only to know intent:
>
> ```
> {full timeline text for the day}
> ```
>
> Decide whether the day's commits made this repo **better, neutral, or worse**. Hardest scrutiny on the **bug-fix commits** — for each, confirm from the diff that it fixes what it claims AND did not: (a) regress another issue, (b) break an untouched consumer of a changed symbol — derive the blast radius yourself (callers, conformances, closures, dynamic dispatch a grep misses), or (c) introduce something big/risky out of proportion to the fix (schema/migration/auth/concurrency/force-unwrap/silenced error). Change NOTHING.
> Return ONLY (no preamble, no recap, no filler — evidence or it's dropped):
> 1. one-line **VERDICT**: `IMPROVED` / `NEUTRAL` / `REGRESSED`.
> 2. **Claim check** — per timeline claim that maps to this repo: matched-by-commit / no-commit-found / commit-contradicts-claim.
> 3. **Findings** the timeline never claimed, each: `[high|med|low] <one-line claim> — evidence: <file:line / git show output / why unverifiable> — so-what: <concrete risk>`. A claim you can't ground is UNVERIFIABLE — say so, don't pad.

## Step 5 — Synthesize the verdict

Collect the auditors' returns. **Re-verify any high-severity finding yourself from source** before repeating it — auditors are input, not verdict (same discipline as `/jstack:audit`). Then:

- **Per app:** `IMPROVED` / `NEUTRAL` / `REGRESSED`, with the one or two findings that drove it.
- **Spine gaps:** claims with no commit (said-shipped, nothing landed), commits with no claim (landed silently).
- **Lead line:** net improvement, or something regressed / shipped risky.

## Step 6 — Write the audit block (always)

Record the verdict on the **audited day's** spine — one block per day, replaced on re-run via the pipeline-task tag. `--at` is the current local time; `--date` is the audited day:

```bash
log_event day-audit --at "$NOW" --date "$DAY" --pipeline-task day-audit#"$DAY" \
  "Day audit: {N} repos with commits — {clean | M regressed / risky}" \
  --detail "{app}: {IMPROVED|NEUTRAL|REGRESSED} — {driver}" \
  --detail "{the single most important finding, or a claim↔commit gap}"
```

Headline ≤120 chars, present-tense, no hashes/paths (timeline format rule). 0–3 detail bullets, ≤80 chars each. No commits that day → a single one-line block: `"Day audit: no commits across {N} repos on {DAY}"`.

## Step 7 — Report to the user

In-session only (nothing else is persisted). Scannable, no filler:

- **Verdict** — one line: net-better, or N apps regressed / risky.
- **Per app** — `IMPROVED / NEUTRAL / REGRESSED`, the finding that drove it, `file:line`.
- **Spine gaps** — claimed-but-not-committed, committed-but-unclaimed.
- **Needs you** — judgment calls you couldn't settle from source, as direct questions.

---

## Rules

- **Report-only on code.** A day audit never edits a repo — it produces a verdict. The *only* write is the one timeline block.
- **Verify from diffs, not from the timeline.** A claim is a pointer, never proof.
- **Owning-agent audits, generic fallback.** Ownership is the agent registry's `repos` per agent; an unowned repo still gets audited (generic), so coverage never drops.
- **Portable.** Repos under `repo_root` (or parent of `agent_root`); ownership from `agent_registry` (or `{agent_root}/agents.json`). Never hardcode a machine's paths.
- **No filler — from the auditors or from you.** Every finding is a falsifiable claim with evidence; re-verify high-severity ones yourself before repeating them.
