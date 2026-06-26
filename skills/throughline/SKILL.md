---
name: throughline
description: Keep a Codex coding agent on its original objective and concrete progress across context compaction. Use at the start of any multi-step task that may run long enough to trigger compaction (refactors, feature builds, migrations, multi-file changes, long autonomous runs), whenever a resumed session has narrowed the objective to "harden/validate/clean up existing code", or whenever compaction causes the agent to repeat already-completed reads, scans, or validation steps. Also use when the user asks to set up anti-drift, an objective card, compaction-storm protection, a compaction safeguard, or throughline hooks.
---

# Throughline

## Overview
Compaction replaces the live transcript with a summary, and long tasks lose both the
original objective and the concrete progress state. This skill keeps an on-disk objective
card as the single source of truth, forces Codex compaction summaries to preserve progress
and completed inputs, and re-injects the card on manual turns and resume. The on-disk card is
the core; the compact prompt is the part that survives in-process compaction. See
[mechanics.md](references/mechanics.md) for why drift happens and the honest limits.

## When to use
Start the card at the beginning of any task that could run long: refactors, feature builds,
migrations, multi-file edits, investigations, or anything autonomous. Reach for it again the
moment a resumed run drifts toward tightening existing behavior instead of doing the asked
change.

## Operating contract (the agent does this without being reminded)
Treat the card as a standing obligation for the whole task, not a one-time setup step. The
user will not prompt you to maintain it; drift happens precisely when no one is watching.
- Create `.throughline.md` on the first substantive turn of any long/multi-step task, before
  deep work, copying the objective verbatim.
- One card per task. A NEW task gets a NEW card: archive the previous card and reset
  OBJECTIVE LOCK, checklist, completed inputs, and decisions. Never carry a finished
  task's objective into the next one; that is the drift this skill exists to stop.
- When a task is done, mark the card `status: done` (or archive it) so the injector goes
  silent instead of feeding a stale objective into the next task.
- After every milestone and before every compaction-prone pause, update the checklist,
  COMPLETED INPUTS / DO-NOT-REPEAT, and NEXT ACTION, then save. This is mandatory, not
  optional polish.
- On resume or after a compaction, re-read the card first and reconcile it with what the
  summary claims. If the summary narrowed the objective, the card wins: restore the original
  objective and continue it.

## Workflow

### 1. Create the card (do this first, every long task)
Use the lifecycle helper so a previous card is archived before the new one is written:
```bash
python3 scripts/card.py init --objective "<verbatim objective>" --task-type feature
python3 scripts/card.py done    # when the task is complete
```
`init` writes `.throughline.md` at the repo root (the hook resolves it by walking up from
cwd) and moves any existing card to `.throughline/archive/<task_id>_<timestamp>.md`. The
disk card is gitignored, so this archive is its only backup. You can still copy
[assets/throughline-card.template.md](assets/throughline-card.template.md) by hand; if the
repo keeps progress docs elsewhere, point `THROUGHLINE_CARD` at that path.

Fill OBJECTIVE LOCK with the user's objective copied word-for-word. Do not paraphrase or
narrow it. List OUT OF SCOPE, the milestone checklist, completed inputs that must not be
repeated, and the next action.

### 2. Keep it bounded (token discipline)
Overwrite in place; never append-grow. Respect the size budget in the template header:
milestones not micro-steps, completed-inputs capped at the last 12 useful facts, decisions
log capped at the last 10 lines, objective stored once.
A bloated card is just another context leak.

### 3. Work the card at every milestone
Before starting a milestone, re-read the card. After finishing one, update the checklist,
COMPLETED INPUTS / DO-NOT-REPEAT, and NEXT ACTION, then save. If current work no longer
serves the objective, write `DRIFT?: <why>` in NEXT ACTION and correct course before
continuing.

### 4. Install the tool hooks (once per machine)
```bash
python3 scripts/install.py
python3 scripts/install.py --print    # preview without writing
```
The installer is idempotent and preserves other tools' hooks. On Codex it writes one managed
block to `config.toml` with `experimental_compact_prompt_file` plus the inline `[hooks.*]`
tables Codex accepts (it never writes the rejected `hooks = "./hooks.json"` form), backs up
`config.toml` first, and clears stray legacy `hooks.json`. See [codex-setup.md](references/codex-setup.md).

### 5. On long/autonomous runs
The card is the anchor because in-process compaction can fire many times without any hook
firing. The compaction prompt must carry forward completed inputs so the next model advances
instead of re-reading large files. If compaction storms persist, reduce noisy tool output and
split to a fresh thread at a milestone, carrying the card forward for a lossless handoff.

## Resources
- `assets/throughline-card.template.md` - the bounded SSOT card to copy per task.
- `assets/compact_prompt.md` - Codex `experimental_compact_prompt_file` content.
- `scripts/throughline_hook.py` - Codex injector; reads the card by cwd, emits additionalContext.
- `scripts/install.py` - idempotent Codex installer/uninstaller.
- `scripts/card.py` - card lifecycle: `init` a new task card (archiving the old one) and `done`.
- `references/` - mechanics and Codex setup.
