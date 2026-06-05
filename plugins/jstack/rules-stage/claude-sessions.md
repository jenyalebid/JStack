---
paths:
  - ".claude/projects/**"
---

# Claude Session Files

**Never read raw JSONL directly** — these files are large and mostly token noise.

## Tools

All scripts at `~/Operations/Infrastructure/scripts/`, run with `.venv/bin/python3`.

**Single session digest:**
```bash
.venv/bin/python3 scripts/review_sessions.py digest <session-id>
```

**List unreviewed sessions for an agent:**
```bash
.venv/bin/python3 scripts/review_sessions.py list <agent>
```

**Stamp session as reviewed:**
```bash
.venv/bin/python3 scripts/review_sessions.py stamp <session-id> <agent>
```
