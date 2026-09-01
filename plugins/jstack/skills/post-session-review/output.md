# Required output

Exact headers, in this order. The engine parses by name; a missing section, or an empty one without per-item citation, is rejected and re-spawned.

```
## TRANSCRIPT_WALK
- turn 1 [HH:MM]: "{first 60 chars of user message}" → {classification} → {citation OR disposition}
- turn 2 [HH:MM]: ...
(every distinct user turn. If there were none, the FIRST line of this section MUST
start with the literal lowercase phrase `no user turns` — e.g.
`no user turns — automation-triggered session (skill payload only)`.)

## DOC_RECONCILE
- {file:line} — {fossil/phantom} — {action taken}
OR
- clean — examined: {docs checked, one line each}; all consistent.

## ACTIONS_TAKEN
- Edit {path:line} — {what changed}
- file-followup "{title}" "{body}"
- ...
OR
- none — {N} user turns walked, {K} docs checked; no action because:
  - {topic 1}: {per-topic reasoning}

## TIMELINE
- log_event {agent}/{submode} --at HH:MM "headline" [--detail "..." --detail "..."]
OR
- none — {routine maintenance / already covered by {seat} block at HH:MM / nothing timeline-worthy}

## SUMMARY
One sentence: the most important thing about this session, or the biggest miss.
```
