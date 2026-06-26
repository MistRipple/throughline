# throughline

English | [中文](README.zh-CN.md)

Keep a Codex coding agent on its **original objective and concrete progress** across
context compaction.

## The problem

When a coding session runs long, Codex compacts its context into a summary. Two failure
modes matter: the summary narrows the goal, or it keeps the goal text but loses concrete
progress. The second mode causes compaction storms: the agent re-reads the same large file,
compacts again, and never reaches the edit or test step.

## The approach

throughline keeps the task state in three layers, ordered by how much they actually help:

1. **On-disk objective card.** The objective, scope, milestones, and next action live in
   `.throughline.md`. Disk content cannot be compacted away.
2. **Codex compaction-time state-lock.** `experimental_compact_prompt_file` forces the
   compaction summary to carry `OBJECTIVE LOCK`, `PROGRESS CHECKLIST`,
   `COMPLETED INPUTS / DO-NOT-REPEAT`, and `NEXT ACTION`.
3. **Injector hook.** Re-feeds the card on manual turns and on `SessionStart`
   startup/resume.

### Honest limit

No hook can intercept *in-process* compaction, which is where long autonomous runs fail. The
Codex compact prompt must carry progress forward during the storm; the disk card helps after
it has been written or injected again. When storms persist, reduce noisy output and split to a
fresh thread at a milestone, carrying the card forward.

Other agent tools are intentionally not wired unless they expose an equivalent compaction
prompt override. throughline focuses on Codex because the protection can be enforced inside
the summary itself.

## Install

```bash
git clone <this-repo> ~/code/throughline
cd ~/code/throughline
./install.sh            # wires Codex hooks + config.toml
./install.sh --print    # preview the hook entries without writing
```

The installer writes one managed block to Codex `config.toml`, bounded by
`# >>> throughline >>>` sentinels, with `experimental_compact_prompt_file` plus the inline
`[hooks.*]` tables Codex actually accepts. It backs up `config.toml` first and removes stray
legacy `hooks.json` from older installs. Codex rejects `hooks = "./hooks.json"`, so
throughline never writes that. See
[codex-setup.md](skills/throughline/references/codex-setup.md).

Uninstall any time: `./install.sh --uninstall`. The installer is idempotent and preserves
other tools' hooks and your own config keys.

## Use

Manage the card with `card.py`; it keeps one card per task and never lets a finished
objective leak into the next one.

1. Start a task. This archives any existing card, then writes a fresh one with your
   objective stored **word-for-word**:
   ```bash
   python3 skills/throughline/scripts/card.py init \
     --objective "the user's request, verbatim" --task-type feature
   ```
2. Work the card. Re-read it before each milestone and update the checklist,
   `COMPLETED INPUTS / DO-NOT-REPEAT`, and `NEXT ACTION` after each. Keep it bounded:
   overwrite in place, never append-grow, respect the size budget. See the field layout in
   [the template](skills/throughline/assets/throughline-card.template.md) and
   [examples/refactor.throughline.md](examples/refactor.throughline.md).
3. Finish the task with `card.py done`. The hook then stays silent until the next `init`,
   so a completed objective never bleeds into new work. Reactivate with `card.py reopen`
   if you picked the task back up.

The previous card is archived to `.throughline/archive/` on every `init` (the disk card is
gitignored, so the archive is its only backup). The card resolves automatically: the hook
walks up from the working directory to find `.throughline.md`, or you can point
`$THROUGHLINE_CARD` at any path.

## Verify

Run deterministic local checks first:

```bash
python3 scripts/verify_local.py
```

Run a live Codex compaction trial when your provider is responsive:

```bash
python3 scripts/run_codex_compaction_trial.py --timeout 900 --keep
python3 scripts/run_codex_compaction_trial.py --compare --timeout 900
python3 scripts/run_codex_compaction_trial.py --isolate --timeout 900
python3 scripts/run_codex_compaction_trial.py --isolate --repeat 3 --timeout 900
```

The live trial creates an isolated `CODEX_HOME` (your real config is never modified),
generates a small refactor task plus a large `NOTES.md` sized to force compaction, then
reports compaction count, whether the last summary contains `OBJECTIVE LOCK` and
`COMPLETED INPUTS / DO-NOT-REPEAT`, whether `Calculator` was produced, and how many card
items were checked. `--compare` runs the default-compaction baseline and throughline back to
back. `--isolate` runs the baseline against the core lever alone (`compact_prompt.md`
enabled, no card and no card-aware prompt).

### Measured results

#### Direct drift test

Live Codex, fixed inline-hooks install, `20000`-token limit to force a compaction storm.
Objective card says **"Build a NEW email notification feature"**; the workspace is salted
with 1500 lines of `harden the existing / clean up existing / tighten legacy` tickets to
actively pull the model toward narrowing.

```bash
python3 scripts/verify_drift.py --modes single,multi,goal --repeat 2 --token-limit 20000
```

Real results from this machine:

| mode | runs | compactions | narrowed to "harden existing" | still naming build target | carried `OBJECTIVE LOCK` |
| --- | --- | --- | --- | --- | --- |
| single | 2 | 51 | **0** | 46 | 40 |
| multi | 2 | 51 | **0** | 49 | 31 |
| goal | 2 | 44 | **0** | 39 | 16 |

Zero drift to "harden existing code" across **146 compactions** in all three modes, under
noise designed to cause exactly that drift. A second independent matrix on the same machine
reproduced it: **0 drift across 159 compactions**.

#### Core lever, isolated

Live `--isolate --repeat 3`, Codex with the configured provider, `60000`-token limit,
NOTES.md sized to fit a single read. The lever has no on-disk card and no card-aware prompt;
the only change vs baseline is the compaction-prompt override.

| mode | runs | compactions (median, range) | completed | summary has OBJECTIVE LOCK | has DO-NOT-REPEAT |
| --- | --- | --- | --- | --- | --- |
| baseline (default compaction) | 3 | 1 (1-2) | 3/3 | 0% | 0% |
| core lever only | 3 | 1 (1-1) | 3/3 | 100% | 100% |

The honest reading: at a budget where the task can finish, the lever does **not** reliably
cut compaction count. The robust difference is the **content of the compaction summary**.
Every lever run reproduced the objective verbatim, marked the NOTES read done, and recorded
`cat NOTES.md` under `COMPLETED INPUTS / DO-NOT-REPEAT`.

#### Brutal-budget compaction storm

Live A/B through Codex, deliberately brutal `40000`-token limit with a ~320KB `NOTES.md`
whose single read alone exceeds the budget.

| run | compactions | refactor completed | final summary preserved objective + DO-NOT-REPEAT |
| --- | --- | --- | --- |
| default baseline | 46 | yes, eventually | no structure |
| throughline | 54 | no (hit the run cap) | yes: OBJECTIVE LOCK + DO-NOT-REPEAT in every summary |

Practical reading: throughline's job is to make every compaction summary carry the objective
and completed work forward. It is **not** a way to survive a budget so small that a single
necessary read will not fit.

## How it's wired

| Layer | Codex |
| --- | --- |
| Objective card | `.throughline.md` on disk |
| Compaction-time state-lock | `experimental_compact_prompt_file` |
| Re-injection | `SessionStart` startup/resume + `UserPromptSubmit` |

## Layout

```text
throughline/
  install.sh
  marketplace.json
  scripts/{verify_local,run_codex_compaction_trial,verify_drift}.py
  examples/refactor.throughline.md
  skills/throughline/
    SKILL.md
    assets/throughline-card.template.md
    assets/compact_prompt.md
    scripts/throughline_hook.py
    scripts/install.py
    references/{mechanics,codex-setup}.md
```

The injector and installer are **stdlib-only Python 3**; no dependencies to install.

## License

MIT. See [LICENSE](LICENSE).
