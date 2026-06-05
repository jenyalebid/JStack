---
paths:
  - ".claude/rules/**"
---

# Writing Claude Rules

Rules live in `~/.claude/rules/`. Markdown with optional YAML frontmatter.

## Format

The **only** supported frontmatter field is `paths` — glob patterns that scope when the rule loads.

- With `paths` → loads on-demand when matching files are read/edited.
- Without `paths` → loads unconditionally at startup. Use sparingly.

## Path syntax

- Relative to whatever Claude Code treats as project root (typically the cwd where `claude` was launched, or the nearest git root). No leading `~/` or absolute `/Users/...` paths.
- `**` for recursive, `*` for single-level, `{ts,tsx}` brace expansion.

## Before creating a rule

- Check existing files in `~/.claude/rules/` for overlaps. One rule per domain.
- Keep rules short — they consume context every time they load.
