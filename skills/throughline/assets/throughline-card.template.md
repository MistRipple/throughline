<!-- throughline card. SSOT for the task's objective + progress across compaction.
     RULES: overwrite-in-place, never append-grow. Keep the whole file under the size
     budget below. This file is re-read at milestones and injected after compaction. -->

# THROUGHLINE

meta:
  task_id: <slug>
  created: <YYYY-MM-DD>
  updated: <YYYY-MM-DD HH:MM>
  size_budget_bytes: 8000   # hard cap; trim oldest decisions if exceeded

## === OBJECTIVE LOCK (verbatim) ===
<!-- The user's original objective, copied word-for-word. NEVER paraphrase, narrow,
     or replace with "harden / validate / clean up existing code". Max ~600 chars. -->
OBJECTIVE: <verbatim original objective>
TASK TYPE: <refactor | feature | bugfix | migration | investigation>

## === OUT OF SCOPE ===
<!-- Things explicitly NOT part of this task. Guards against scope creep after compaction. -->
- <item>

## === PROGRESS CHECKLIST ===
<!-- Milestones only, not micro-steps. Keep <= 20 items. Preserve original order + wording.
     Status: [x] done  [~] in progress  [ ] not started -->
- [ ] <milestone 1>
- [ ] <milestone 2>

## === NEXT ACTION ===
<!-- One concrete next step. If you suspect drift (current work no longer serves the
     OBJECTIVE), write "DRIFT?: <why>" here instead of a step. -->
<next step>

## === DECISIONS (bounded, last 10) ===
<!-- Newest on top; delete entries beyond 10 to respect the size budget.
     One line each: date | decision | reason. -->
- <YYYY-MM-DD> | <decision> | <reason>
