# Filing an issue

Resolve the owning repo from where the problem lives, not where you stand:
`git -C "$(dirname <file>)" rev-parse --show-toplevel` → its origin. No owner: the home repo.

Search before filing. A recurrence gets a comment on the open issue, not a second number:

`gh issue list --repo <owner/name> --search "<distinctive words>" --state all --limit 10`

Write the body to a file, then:

`file-issue --repo <owner/name> --title "<t>" --body-file <p> --label <bug|optimization|feature>`

One label: `bug` = broken · `optimization` = works, should be better · `feature` = doesn't exist yet. Success prints `ISSUE <url> board=<col|none> type=<label>`; `board=none` is normal. On non-zero exit report the failure — never a number you did not get back.

Write the body for someone who was not here and must act on it without asking a question:

- what's wrong, stated as behaviour
- where
- how to see it — say plainly if it was reasoned out rather than reproduced
- why it matters
- fix direction, or `unknown — needs investigation`
- `Found during:` task, seat, date

Title: one sentence naming the symptom, readable cold. Not the file, not the fix.
