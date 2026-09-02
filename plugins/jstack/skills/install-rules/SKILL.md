---
name: install-rules
description: Use when the user asks to install or refresh the JStack rules and bare slash commands in ~/.claude/.
argument-hint: "[--copy] [--force]"
---

# /jstack:install-rules — install what the plugin can't ship

Two things load only from fixed user-scope locations, so a plugin cannot deliver them:
path-matched rules (`~/.claude/rules/`) and unnamespaced slash commands
(`~/.claude/commands/` — a plugin's own commands are always `/jstack:name`). This skill
links both out of the plugin's staging directories.

## Arguments

- (none) — symlink, skipping anything already there
- `--copy` — copy instead, so local edits don't touch the plugin source
- `--force` — overwrite what exists, and skip the confirmation

## Procedure

**Sources.** `${CLAUDE_PLUGIN_ROOT}` is substituted to the install directory at runtime —
use it directly, don't parse `installed_plugins.json`:

```
${CLAUDE_PLUGIN_ROOT}/rules-stage/*.md      →  ~/.claude/rules/
${CLAUDE_PLUGIN_ROOT}/commands-stage/*.md   →  ~/.claude/commands/
```

Running from a raw clone with the plugin disabled leaves `${CLAUDE_PLUGIN_ROOT}` unset —
fall back to the staging dirs beside this skill, or ask where the clone lives.

**Confirm.** Enumerate both stages at runtime and show the counts and the destinations,
then wait for one word (`yes` / `y` / `go`). `--force` skips the ask.

**Install.** Per file: `mkdir -p` the destination, skip if it exists and `--force` wasn't
passed, then `cp` or `ln -sf`.

Point symlinks at the **checkout**, not the versioned cache path — the cache directory
changes on every version bump and old ones are reaped, so links into it go dead on
update. A link into the checkout tracks every future change for free. Prefer `--copy`
only when the machine has no checkout.

**Report.** One line per file — `installed` / `skipped (exists)` / `failed (<reason>)` —
then the totals.

## Uninstall

Remove only the links that still point into a jstack stage, in both destinations:

```bash
for f in ~/.claude/rules/*.md ~/.claude/commands/*.md; do
  [ -L "$f" ] && readlink "$f" | grep -q "jstack/.*-stage" && rm "$f"
done
```
