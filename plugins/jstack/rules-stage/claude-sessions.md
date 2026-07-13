---
paths:
  - ".claude/projects/**"
---

# Claude Session Files

**Never read raw session JSONL directly** — transcript files are large and mostly token noise; a full read can blow the context window.

## Working with transcripts

- **This session's own transcript path**: `/jstack:print` emits it.
- **Extract, don't read.** Pull only what you need with `jq` — e.g. the last N user/assistant texts:

```bash
jq -r 'select(.type == "user" or .type == "assistant") | .message.content | if type == "array" then .[] | select(.type == "text") | .text else . end' <session>.jsonl | tail -50
```

- **Counts / shape first**: `wc -l`, `jq -r .type | sort | uniq -c` — decide what to extract before extracting.
- Reviewing a finished session is what the jstack session-review engine and `/jstack:post-session-review <session-id>` are for — prefer them over hand-parsing.
