---
name: throughline
description: Keep a coding agent on its original objective and concrete progress across context compaction, for both Codex and Claude Code. Use at the start of any multi-step task that may run long enough to trigger compaction (refactors, feature builds, migrations, multi-file changes, long autonomous runs), whenever a resumed session has narrowed the objective to "harden/validate/clean up existing code", or whenever compaction causes the agent to repeat already-completed reads, scans, or validation steps. Also use when the user asks to set up anti-drift, an objective card, compaction-storm protection, a compaction safeguard, or throughline hooks.
---

# Throughline

## Overview
Compaction replaces the live transcript with a summary, and long tasks lose both the
original objective and the concrete progress state. This skill keeps an on-disk objective
card as the single source of truth, forces compaction summaries to preserve progress and
completed inputs, and re-injects the card on manual turns and resume. The on-disk card is
the core; the tool-specific hooks are reinforcement. See [mechanics.md](references/mechanics.md)
for why drift happens and the honest limits.

## When to use
Start the card at the beginning of any task that could run long: refactors, feature builds,
migrations, multi-file edits, investigations, or anything autonomous. Reach for it again the
moment a resumed run drifts toward tightening existing behavior instead of doing the asked
change.

## Workflow

### 1. Create the card (do this first, every long task)
Copy [assets/throughline-card.template.md](assets/throughline-card.template.md) to
`.throughline.md` at the repo root (the hook resolves it by walking up from cwd). If the repo
keeps progress docs elsewhere (e.g. `docs/engineering/`), put the real card there and either
symlink `.throughline.md` to it or set `THROUGHLINE_CARD` to its path.

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
python3 scripts/install.py            # both tools
python3 scripts/install.py --codex    # or one
python3 scripts/install.py --print    # preview without writing
```
The installer is idempotent and preserves other tools' hooks. Then finish tool wiring:
- Codex: add `experimental_compact_prompt_file` (the compaction state-lock) and `hooks = "./hooks.json"` to `config.toml`. See [codex-setup.md](references/codex-setup.md).
- Claude: add a `PreCompact` snapshot; the `SessionStart:compact` hook re-injects after. See [claude-setup.md](references/claude-setup.md).

### 5. On long/autonomous runs
The card is the anchor because in-process compaction can fire many times without any hook
firing. The compaction prompt must carry forward completed inputs so the next model advances
instead of re-reading large files. If compaction storms persist, reduce noisy tool output and
split to a fresh thread at a milestone, carrying the card forward for a lossless handoff.

## Resources
- `assets/throughline-card.template.md` - the bounded SSOT card to copy per task.
- `assets/compact_prompt.md` - Codex `experimental_compact_prompt_file` content.
- `scripts/throughline_hook.py` - injector (Codex + Claude); reads the card by cwd, emits additionalContext.
- `scripts/install.py` - idempotent installer/uninstaller for both tools.
- `references/` - mechanics, Codex setup, Claude setup.
