# Why throughline works (and what actually causes drift)

## The failure mode
After context compaction, the live transcript is replaced by a summary. Two things go
wrong with long autonomous runs:

1. Objective narrowing. Summaries tend to compress an active "build X / refactor to Y"
   objective into "improve the existing code," so the resumed model starts tightening or
   validating current behavior instead of finishing the original change.
2. Progress loss. The goal text survives, but completed reads, scans, and confirmations are
   forgotten, so the resumed model keeps repeating the same setup step.
3. Summary-of-summary degradation. Under heavy pressure ("compaction storms") the model
   re-summarizes its own summaries repeatedly; the working set no longer fits and the
   original objective decays a little each pass until it is gone.

Observed in testing: in a single autonomous turn, compaction fired dozens of times while a
manual user turn fired once. So anything that only runs on user turns cannot be the primary
safeguard.

## The layers that matter
- On-disk objective card (SSOT). The objective, scope, milestones, and next action live in a
  file on disk, not only in context. Disk content cannot be compacted away. This is the
  universal core and the part that carries long runs.
- Compaction-time state-lock. The summary the model produces at compaction is forced to
  start with OBJECTIVE LOCK, PROGRESS CHECKLIST, COMPLETED INPUTS / DO-NOT-REPEAT, and NEXT
  ACTION. Objective text alone is insufficient; the completed-inputs section is what prevents
  large-file re-read loops.
- Resume injection. The hook re-feeds the disk card on manual turns and on resume/session
  start. This is useful for human-in-the-loop handoffs and restarts.

Observed in testing: default Codex may keep the original objective through many compactions
and still fail because the agent repeats the same "read the big file" step. throughline must
preserve concrete progress, not just the task headline.

## Honest limits
No hook can intercept in-process compaction, which is where most drift happens on long
autonomous runs. The Codex compact prompt must carry the live progress summary forward. The
disk card helps only after it has been written or injected again. Under genuine compaction
storms, reduce noisy tool output and split to a fresh thread at a milestone, carrying the
card forward.

## Token budget discipline
The card is bounded on purpose so it does not become a second context leak:
- Overwrite-in-place. Never append-grow. Update the same sections each milestone.
- Hard size budget (default 8 KB in the template; injector caps injection at ~9 KB).
- Milestones only, not micro-steps; completed-inputs capped to the last 12 useful facts;
  decisions log capped to the last 10 lines.
- The objective is stored once, verbatim, and never rewritten.
