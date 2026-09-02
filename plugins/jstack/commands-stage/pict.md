---
name: pict
description: Use only if /pict was typed and the JStack hook did not answer it.
argument-hint: "[dir] [--full] [pict flags]"
---

JSTACK_PICT_CMD $ARGUMENTS

---

**If you are reading this, the hook did not fire.** `hooks/pict-command.py` normally
intercepts this prompt and answers it without starting a turn; reaching the model
means it is not wired, not executable, or this Claude Code version does not run
`UserPromptSubmit` for slash commands. Say so in one line, then do the work by hand:
`pict <dir> --bare` into `<workspace>/pad/pict-<dir>.md` (a directory the viewer can
read — a render outside it opens onto a refusal), then `show-doc <file> --title
"<dir> · pict"`, or `open-artifact <file>` where there is no `show-doc`. `--full`
drops `--bare` for the annotated view.

Never describe, summarise, or draw what a seat loads. An account written from what
you believe is in your context is a guess, and replacing that guess is the whole
point of the tool.
