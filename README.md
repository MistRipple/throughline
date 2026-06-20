# throughline

Keep a coding agent on its **original objective** across context compaction. Works with both
**Codex** and **Claude Code**.

## The problem

When a coding session runs long, the agent compacts its context into a summary. On long or
autonomous runs this summary quietly **narrows the goal**: a task that started as "refactor X
into Y" turns into "harden / validate / clean up the existing code," and the original
objective never gets finished. Under heavy pressure ("compaction storms") the model
re-summarizes its own summaries until the objective decays away entirely.

## The approach

throughline keeps the objective in three layers, ordered by how much they actually help:

1. **On-disk objective card (the core).** The objective, scope, milestones, and next action
   live in a file on disk (`.throughline.md`). Disk content cannot be compacted away.
2. **Compaction-time objective-lock.** The summary the agent writes at compaction is forced to
   begin with a verbatim `OBJECTIVE LOCK` block. On Codex this is a real prompt override; on
   Claude the card carries this load with a `PreCompact` snapshot.
3. **Injector hook.** Re-feeds the card on manual turns and on resume/session start. Same hook
   serves both tools.

### Honest limit

No hook can intercept *in-process* compaction, which is where most drift happens on long
autonomous runs. The disk card plus the Codex objective-lock prompt are what survive those
storms. When storms persist, the durable cure is reducing noisy output and splitting to a
fresh thread at a milestone, carrying the card forward.

## Install

```bash
git clone <this-repo> ~/code/throughline
cd ~/code/throughline
./install.sh            # wires the hook into Codex + Claude
./install.sh --print    # preview the hook entries without writing
```

Then finish the tool-specific wiring (the high-value part):

- **Codex**: in `~/.codex/config.toml` set
  `experimental_compact_prompt_file = ".../skills/throughline/assets/compact_prompt.md"`
  and `hooks = "./hooks.json"`. See
  [codex-setup.md](skills/throughline/references/codex-setup.md).
- **Claude**: add a `PreCompact` snapshot; the `SessionStart:compact` hook re-injects after.
  See [claude-setup.md](skills/throughline/references/claude-setup.md).

Uninstall any time: `./install.sh --uninstall`. The installer is idempotent and preserves
other tools' hooks.

## Use

1. At the start of a long task, copy
   [the template](skills/throughline/assets/throughline-card.template.md) to `.throughline.md`
   at your repo root and fill in `OBJECTIVE LOCK` with the user's request **word-for-word**.
   See [examples/refactor.throughline.md](examples/refactor.throughline.md).
2. Re-read the card before each milestone; update the checklist and `NEXT ACTION` after each.
3. Keep it bounded: overwrite in place, never append-grow, respect the size budget.

The card resolves automatically: the hook walks up from the working directory to find
`.throughline.md`, or you can point `$THROUGHLINE_CARD` at any path.

## How it's wired

| Layer | Codex | Claude Code |
| --- | --- | --- |
| Objective card (SSOT) | `.throughline.md` on disk | `.throughline.md` on disk |
| Compaction-time lock | `experimental_compact_prompt_file` | `PreCompact` snapshot |
| Re-injection | `SessionStart` (startup/resume) + `UserPromptSubmit` | `SessionStart` (startup/resume/**compact**) + `UserPromptSubmit` |

## Layout

```
throughline/
  install.sh
  marketplace.json
  examples/refactor.throughline.md
  skills/throughline/
    SKILL.md
    assets/throughline-card.template.md
    assets/compact_prompt.md
    scripts/throughline_hook.py
    scripts/install.py
    references/{mechanics,codex-setup,claude-setup}.md
```

The injector and installer are **stdlib-only Python 3**; no dependencies to install.

## License

MIT. See [LICENSE](LICENSE).
