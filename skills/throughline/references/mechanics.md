# Why throughline works (and what actually causes drift)

## The failure mode
After context compaction, the live transcript is replaced by a summary. Two things go
wrong with long autonomous runs:

1. Objective narrowing. Summaries tend to compress an active "build X / refactor to Y"
   objective into "improve the existing code," so the resumed model starts tightening or
   validating current behavior instead of finishing the original change.
2. Summary-of-summary degradation. Under heavy pressure ("compaction storms") the model
   re-summarizes its own summaries repeatedly; the working set no longer fits and the
   original objective decays a little each pass until it is gone.

Observed in testing: in a single autonomous turn, compaction fired dozens of times while a
manual user turn fired once. So anything that only runs on user turns cannot be the primary
safeguard.

## The two layers that matter
- On-disk objective card (SSOT). The objective, scope, milestones, and next action live in a
  file on disk, not only in context. Disk content cannot be compacted away. This is the
  universal core and the part that carries long runs.
- Compaction-time objective-lock. The summary the model produces at compaction is forced to
  start with a verbatim OBJECTIVE LOCK block, so even the in-context summary keeps the real
  objective. Codex and Claude expose different controls for this (see their setup files).

The injector hook is a third, smaller layer: it re-feeds the card on manual turns and on
resume/session start. Useful, but not sufficient alone, because it does not fire mid-run.

## Honest limits
No hook can intercept in-process compaction, which is where most drift happens on long
autonomous runs. The disk card plus the Codex objective-lock prompt are what survive those
storms. Under genuine compaction storms the durable cure is to reduce noisy tool output and
split to a fresh thread at a milestone, carrying the card forward.

## Token budget discipline
The card is bounded on purpose so it does not become a second context leak:
- Overwrite-in-place. Never append-grow. Update the same sections each milestone.
- Hard size budget (default 8 KB in the template; injector caps injection at ~9 KB).
- Milestones only, not micro-steps; decisions log capped to the last 10 lines.
- The objective is stored once, verbatim, and never rewritten.
