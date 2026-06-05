---
name: install-rules
description: Symlink JStack-bundled rules into ~/.claude/rules/ so they auto-load by glob match.
argument-hint: "[--copy] [--force]"
---

# /jstack:install-rules — install JStack rules into ~/.claude/rules/

Claude Code plugins don't natively ship `~/.claude/rules/*.md` content (rules auto-load by glob match from a fixed location). This skill bridges the gap: it symlinks each rule file from the plugin's `rules-stage/` directory into `~/.claude/rules/`.

## Arguments

- (no arg) — symlink (default), skip files that already exist
- `--copy` — copy instead of symlink (good if you want to edit locally without affecting the plugin source)
- `--force` — overwrite existing files in `~/.claude/rules/`

## Procedure

### Step 1 — Locate the rule source

The plugin's rule stage lives at:

```
<plugin_install_path>/rules-stage/*.md
```

Where `<plugin_install_path>` is typically `~/.claude/plugins/cache/<marketplace>/jstack/<version>/`. Resolve it by inspecting `~/.claude/plugins/installed_plugins.json` — find the `jstack@<marketplace>` entry, read its `installPath`.

If the entry isn't found, tell the user:

> JStack plugin not installed via marketplace. Rules are at `~/JStack/plugins/jstack/rules-stage/` if you cloned the repo directly.

### Step 2 — Confirm with the user

List the rules to install:

```
Installing N rules into ~/.claude/rules/:
  - canvas.md
  - claude-md-editing.md
  - claude-sessions.md
  - code-review.md
  - execution-gates.md
  - ios-screens.md
  - ios-sheets.md
  - ios-style.md
  - rules.md
  - visual-assets.md
  - x-compound-tools.md

Mode: symlink (use --copy for copies, --force to overwrite existing)
```

Wait for user confirmation (one word: `yes` / `y` / `go`) unless `--force` was passed.

### Step 3 — Install

For each `<rule>.md` in `rules-stage/`:

```bash
DEST=~/.claude/rules/<rule>.md
if [ -e "$DEST" ] && [ -z "$FORCE" ]; then
  echo "skip: $DEST exists"
  continue
fi
mkdir -p ~/.claude/rules
if [ "$MODE" = "copy" ]; then
  cp <source>/<rule>.md "$DEST"
else
  ln -sf <source>/<rule>.md "$DEST"
fi
```

### Step 4 — Report

One line per rule: `installed: <name>` / `skipped: <name> (exists)` / `failed: <name> (<reason>)`.

Final summary: `N installed, M skipped, K failed.`

## Why not just install at plugin install time?

Plugins don't have a post-install hook surface (yet). And rules are a user-scope concern — the user should opt in. This skill makes opt-in one slash command.

## Uninstall

To remove the symlinks later, the user runs:

```bash
for f in ~/JStack/plugins/jstack/rules-stage/*.md; do
  name=$(basename "$f")
  target=~/.claude/rules/$name
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$f" ]; then
    rm "$target"
  fi
done
```

(No `/jstack:uninstall-rules` skill — too niche to bake in.)
