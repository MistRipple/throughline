You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another
LLM that will resume this exact task. The resuming model will see ONLY your summary, so
state fidelity matters more than narrative detail.

Your summary MUST begin with the following fixed block, filled in, before any prose:

=== OBJECTIVE LOCK (verbatim) ===
ORIGINAL OBJECTIVE: <the user's original objective, copied word-for-word from the first
  user request that defined this task. Do NOT paraphrase, summarize, narrow, or "improve" it.>
TASK TYPE: <refactor | feature | bugfix | migration | investigation>
OUT OF SCOPE: <anything the user explicitly excluded, or "none stated">

=== PROGRESS CHECKLIST ===
<Milestones toward the ORIGINAL OBJECTIVE, preserving their original order and wording.
 Mark each: [x] done  [~] in progress  [ ] not started. Milestones only, not micro-steps.
 Carry forward any status from the live transcript, prior compaction summary, or throughline
 card. NEVER reset all items to unchecked unless there is evidence that nothing happened.>

=== COMPLETED INPUTS / DO-NOT-REPEAT ===
<List expensive reads, scans, investigations, and confirmations already completed.
 Include file path, command/evidence, and conclusion. If a large file was already read or
 verified and has not changed, tell the next model to use this digest and advance.>

=== NEXT ACTION ===
<The single most important next step that advances the ORIGINAL OBJECTIVE and the first
 unchecked or in-progress checklist item. Do not choose an action from COMPLETED INPUTS.>

Then continue with the normal handoff detail: key files touched, decisions made, test
state, open questions, and any tool/session state needed to resume.

HARD RULES:
- Reproduce ORIGINAL OBJECTIVE verbatim. If you cannot find it, say so explicitly under
  OBJECTIVE LOCK rather than inventing one.
- NEVER silently replace the objective with "harden, validate, clean up, or tighten the
  existing code" unless the user actually asked for that. Building or refactoring toward
  new behavior is the default objective and must survive compaction.
- If the current work has drifted away from the ORIGINAL OBJECTIVE, do not hide it: write
  "DRIFT DETECTED: <explanation>" as the first line under NEXT ACTION.
- If a throughline card file exists on disk for this task, treat it as the source of truth
  for ORIGINAL OBJECTIVE and OUT OF SCOPE.
- Preserve progress over politeness. If NOTES.md, docs, test output, repo maps, or other
  large inputs were already read in this turn or in a prior summary, summarize their useful
  conclusions under COMPLETED INPUTS / DO-NOT-REPEAT and mark that milestone done.
- Never make the next model re-read a large file just to be safe. Re-read only when the file
  changed after the recorded evidence or when the conclusion is missing.
- If the previous assistant failed to update the throughline card, infer progress from the
  transcript and say "CARD STALE: update it after the next concrete change" in NEXT ACTION.
- The next action must be executable immediately. Prefer editing, testing, or updating the
  card over another broad review step when the completed inputs already cover the review.
