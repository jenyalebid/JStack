---
paths:
  - "Operations/Infrastructure/lib/iphone_tools.py"
  - "Archive/Skills/x-*"
---

# X Platform — Compound Tools Pattern

## Problem
X (Twitter) uses a heavy React Native DOM (200-370 accessibility elements). Individual WDA calls (tap, read, scroll, type) fail constantly — elements shift, load late, overlap. A 5-step like operation had ~50% failure rate per step, meaning <3% success for the full action.

## Solution: Compound Tools
High-level tools that collapse 5-10 WDA calls into a single atomic operation with built-in retry, verification, and error handling:

| Tool | What it does | WDA calls collapsed |
|------|-------------|-------------------|
| `iphone_x_like` | Find tweet, scroll to it, tap like, verify | ~6 |
| `iphone_x_reply` | Find tweet, open reply, type, post, verify | ~8 |
| `iphone_x_follow` | Find user, tap follow, verify state change | ~5 |
| `iphone_x_search` | Navigate to search, type query, wait for results | ~6 |
| `iphone_x_post` | Open composer, type, post, verify, record | ~7 |

Each tool handles its own navigation, waits, retries, and verification. The model calls one tool instead of orchestrating a fragile sequence.

## Engagement Enforcement Layer
Budgets and pacing are enforced in Python (persists across Qwen context wipes):

- **Budget caps**: Per-session randomized limits (likes: 8-15, replies: 3-5, follows: 2-5)
- **Pacing delays**: Random 8-15s between actions
- **Variety gates**: Must alternate action types (can't spam 10 likes in a row)
- **Browse gaps**: Forced scroll-only periods between engagement bursts
- **Reply dedup**: 12h cooldown per user, hard gate in handler

## Results
First X session: 33 successful actions, 1 error. Before compound tools: constant WDA failures made X sessions unusable.

## When editing
- Keep compound tools atomic — one high-level action per tool
- All enforcement lives in Python, not in prompts or model instructions
- Characters call the compound tool; they never orchestrate raw WDA sequences on X
- Budget state resets per session, not per context wipe
