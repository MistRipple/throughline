You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary for another
LLM that will resume this exact task. The resuming model will see ONLY your summary, so
objective fidelity matters more than narrative detail.

Your summary MUST begin with the following fixed block, filled in, before any prose:

=== OBJECTIVE LOCK (verbatim) ===
ORIGINAL OBJECTIVE: <the user's original objective, copied word-for-word from the first
  user request that defined this task. Do NOT paraphrase, summarize, narrow, or "improve" it.>
TASK TYPE: <refactor | feature | bugfix | migration | investigation>
OUT OF SCOPE: <anything the user explicitly excluded, or "none stated">

=== PROGRESS CHECKLIST ===
<Milestones toward the ORIGINAL OBJECTIVE, preserving their original order and wording.
 Mark each: [x] done  [~] in progress  [ ] not started. Milestones only, not micro-steps.>

=== NEXT ACTION ===
<The single most important next step that advances the ORIGINAL OBJECTIVE.>

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
