# External mode

Replaces steps 2–4: the auditor reports its verdict to the user in its own terminal, with full context separation.

Write the brief as in step 1, then show it and wait a beat for the user to correct a wrong premise before opening the terminal.

`open-terminal-here` flattens its arguments into a shell string, so the kickoff prompt carries its own escaped quoting:

```bash
open-terminal-here "$TARGET_CWD" --append-system-prompt-file "$TARGET_CWD/audit-brief.md" "\"Audit session. Your system prompt carries an Audit Protocol and an Audit Brief. Follow the protocol: if genuinely blocked, ask now; otherwise begin the audit immediately and report your verdict here.\""
```

Nonzero exit — no supported terminal, unsupported platform — means no auditor started. Give the user the brief's absolute path and tell them to open a session there with `--append-system-prompt-file audit-brief.md`.

The brief lives in the target workspace, so each agent keeps its own and the new session loads the CLAUDE.md walk-up from there.
