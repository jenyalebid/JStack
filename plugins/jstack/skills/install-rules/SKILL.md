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
${CLAUDE_PLUGIN_ROOT}/rules-stage/*.md
```

`${CLAUDE_PLUGIN_ROOT}` is substituted to this plugin's install directory at runtime — no need to parse `installed_plugins.json`. Use it directly as the symlink/copy source.

If `${CLAUDE_PLUGIN_ROOT}/rules-stage/` doesn't exist (e.g. running from a raw clone without the plugin enabled), fall back to the `rules-stage/` directory next to this skill, or tell the user where their clone lives.

### Step 2 — Confirm with the user

List the rules to install:

```
Installing N rules into ~/.claude/rules/:
  - canvas.md
  - claude-md-editing.md
  - claude-sessions.md
  - code-review.md
  - execution-gates.md
  - ios-charts.md
  - ios-forms.md
  - ios-lists.md
  - ios-modifiers.md
  - ios-screens.md
  - ios-services.md
  - ios-sheets.md
  - ios-style.md
  - rules.md
  - visual-assets.md
  - x-compound-tools.md

Mode: symlink (use --copy for copies, --force to overwrite existing)
```

The skill enumerates `${CLAUDE_PLUGIN_ROOT}/rules-stage/*.md` at runtime — the list above is illustrative; whatever is in `rules-stage/` is what gets installed.

Wait for user confirmation (one word: `yes` / `y` / `go`) unless `--force` was passed.

### Step 3 — Install

For each `<rule>.md` in `${CLAUDE_PLUGIN_ROOT}/rules-stage/`:

```bash
SRC="${CLAUDE_PLUGIN_ROOT}/rules-stage"
mkdir -p ~/.claude/rules
DEST=~/.claude/rules/<rule>.md
if [ -e "$DEST" ] && [ -z "$FORCE" ]; then
  echo "skip: $DEST exists"
  continue
fi
if [ "$MODE" = "copy" ]; then
  cp "$SRC/<rule>.md" "$DEST"
else
  ln -sf "$SRC/<rule>.md" "$DEST"
fi
```

Symlinks point into the plugin cache, so they auto-track plugin updates. Note the install path changes on version bumps (old version is cleaned up ~7 days later) — re-run `/jstack:install-rules --force` after a major update to re-point symlinks, or use `--copy` for update-independent local copies.

### Step 4 — Report

One line per rule: `installed: <name>` / `skipped: <name> (exists)` / `failed: <name> (<reason>)`.

Final summary: `N installed, M skipped, K failed.`

## Why not just install at plugin install time?

Plugins don't have a post-install hook surface (yet). And rules are a user-scope concern — the user should opt in. This skill makes opt-in one slash command.

## Uninstall

To remove the symlinks later, the user runs (removes only rule symlinks that still point into a jstack plugin install):

```bash
for f in ~/.claude/rules/*.md; do
  [ -L "$f" ] && readlink "$f" | grep -q "jstack/rules-stage" && rm "$f"
done
```

(No `/jstack:uninstall-rules` skill — too niche to bake in.)
