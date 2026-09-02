---
name: tag
description: File this session under a timeline subject. Runs in the JStack UserPromptSubmit hook — no model turn.
argument-hint: "[name] | [name <description, to mint>] | -[name]"
---

JSTACK_TAG_CMD $ARGUMENTS

---

**If you are reading this, the hook did not fire.** `hooks/tag-command.py` normally
intercepts this prompt and answers it without starting a turn; reaching the model
means it is not wired, not executable, or this Claude Code version does not run
`UserPromptSubmit` for slash commands. Say so in one line, then do the work by hand
with `log_event`: bare → `tag list`; a name this session already carries (`●`) →
`tag unset`; a known name → `tag set`; an unknown name with trailing words →
`tag new <name> --description "<words>"` then `tag set`; an unknown name alone →
ask for the description rather than minting a tag nobody can match against.
