"""How a zero-turn command answers the user and stops the prompt.

Shared by every `UserPromptSubmit` hook that IS a command — `/tag`, `/pict` —
because the thing they have in common is not their work, it is this protocol
with the harness, and two copies of a protocol drift.

**Two channels, one answer, and the block is guaranteed by neither alone.**

- **stdout, as JSON.** `decision: "block"` hands the harness our text as the
  whole reason, so what lands on screen is the answer and nothing else. Left
  to itself the harness builds the reason as ``[<the hook's command>]: <stderr>``
  — which is why the first line of a bare `/tag` used to arrive welded to the
  path of the script that printed it. `suppressOriginalPrompt` drops the
  `Original prompt: /tag` echo that otherwise follows underneath.
- **stderr, as text, and exit 2.** The path a harness that ignores the JSON
  takes. It blocks, and it shows the same words — with the old prefix back.

So the exit code is what stops the turn and the JSON is what makes the answer
readable. A version that stops understanding one still has the other.

One line the hook cannot remove: `UserPromptSubmit operation blocked by hook:`
is printed by Claude Code above the reason, on the block path, unconditionally.
The alternative (`continue: false`) trades it for `Operation stopped by hook:`
*and* pushes the text into the conversation as a meta message — a worse deal on
both counts, since the whole point is to spend no context.
"""

import json
import sys

#: The event these hooks answer on. Claude Code rejects a `hookSpecificOutput`
#: whose `hookEventName` disagrees with the event actually firing, so this is
#: pinned here rather than passed in — there is one right value.
EVENT = "UserPromptSubmit"


def block(message: str) -> "None":
    """Say `message` to the user and stop the prompt. Never returns."""
    text = message.rstrip()
    print(json.dumps({
        "decision": "block",
        "reason": text,
        # Our stdout is machinery, not a message — the answer is `reason`.
        "suppressOutput": True,
        "hookSpecificOutput": {
            "hookEventName": EVENT,
            "suppressOriginalPrompt": True,
        },
    }))
    print(text, file=sys.stderr)
    sys.exit(2)
