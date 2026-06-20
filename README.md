# throughline

Keep a coding agent on its **original objective and concrete progress** across context
compaction. Works with both **Codex** and **Claude Code**.

## The problem

When a coding session runs long, the agent compacts its context into a summary. Two failure
modes matter: the summary narrows the goal, or it keeps the goal text but loses concrete
progress. The second mode causes compaction storms: the agent re-reads the same large file,
compacts again, and never reaches the edit or test step.

## The approach

throughline keeps the task state in three layers, ordered by how much they actually help:

1. **On-disk objective card (the core).** The objective, scope, milestones, and next action
   live in a file on disk (`.throughline.md`). Disk content cannot be compacted away.
2. **Compaction-time state-lock.** The summary the agent writes at compaction is forced to
   carry `OBJECTIVE LOCK`, `PROGRESS CHECKLIST`, `COMPLETED INPUTS / DO-NOT-REPEAT`, and
   `NEXT ACTION`. On Codex this is a real prompt override; on Claude the card carries this
   load with a `PreCompact` snapshot.
3. **Injector hook.** Re-feeds the card on manual turns and on resume/session start. Same hook
   serves both tools.

### Honest limit

No hook can intercept *in-process* compaction, which is where long autonomous runs fail. The
Codex compact prompt must carry progress forward during the storm; the disk card helps after
it has been written or injected again. When storms persist, reduce noisy output and split to a
fresh thread at a milestone, carrying the card forward.

## Install

```bash
git clone <this-repo> ~/code/throughline
cd ~/code/throughline
./install.sh            # wires Codex + Claude (hooks + Codex config.toml)
./install.sh --print    # preview the hook entries without writing
```

On **Codex** the installer also wires `config.toml` for you: it adds
`experimental_compact_prompt_file` (the compaction state-lock) and `hooks = "./hooks.json"`
above the first `[table]`, backs up `config.toml` first, and keeps any value you already set.
See [codex-setup.md](skills/throughline/references/codex-setup.md).
On **Claude**, add a `PreCompact` snapshot; the `SessionStart:compact` hook re-injects after.
See [claude-setup.md](skills/throughline/references/claude-setup.md).

Uninstall any time: `./install.sh --uninstall`. The installer is idempotent and preserves
other tools' hooks and your own config keys.

## Use

1. At the start of a long task, copy
   [the template](skills/throughline/assets/throughline-card.template.md) to `.throughline.md`
   at your repo root and fill in `OBJECTIVE LOCK` with the user's request **word-for-word**.
   See [examples/refactor.throughline.md](examples/refactor.throughline.md).
2. Re-read the card before each milestone; update the checklist, `COMPLETED INPUTS /
   DO-NOT-REPEAT`, and `NEXT ACTION` after each.
3. Keep it bounded: overwrite in place, never append-grow, respect the size budget.

The card resolves automatically: the hook walks up from the working directory to find
`.throughline.md`, or you can point `$THROUGHLINE_CARD` at any path.

## Verify

Run deterministic local checks first:

```bash
python3 scripts/verify_local.py
```

Run a live Codex compaction trial when your provider is responsive:

```bash
python3 scripts/run_codex_compaction_trial.py --timeout 900 --keep            # throughline only
python3 scripts/run_codex_compaction_trial.py --compare --timeout 900         # A/B vs default
python3 scripts/run_codex_compaction_trial.py --isolate --timeout 900         # baseline vs core lever only
python3 scripts/run_codex_compaction_trial.py --isolate --repeat 3 --timeout 900  # medians over 3 runs each
```

The live trial creates an isolated `CODEX_HOME` (your real config is never modified),
generates a small refactor task plus a large `NOTES.md` sized to force compaction, then
reports compaction count, whether the last summary contains `OBJECTIVE LOCK` and
`COMPLETED INPUTS / DO-NOT-REPEAT`, whether `Calculator` was produced, and how many card
items were checked. `--compare` runs the default-compaction baseline and throughline
back to back and prints an A/B table.
`--isolate` runs the baseline against the **core lever alone** (`compact_prompt.md` enabled,
no card and no card-aware prompt), so any difference is attributable to the compaction-prompt
override by itself.
`--repeat N` runs each mode N times and reports the median compaction count, the range, the
completion rate, and the share of runs whose final summary carried `OBJECTIVE LOCK` and
`COMPLETED INPUTS / DO-NOT-REPEAT`, so the numbers below are medians rather than single runs.

### Measured results

#### Core lever, isolated (the part that survives in-process compaction)

Live `--isolate --repeat 3`, Claude Opus 4.8 provider, `60000`-token limit, NOTES.md sized to
fit a single read. The lever has no on-disk card and no card-aware prompt; the only change vs
baseline is the compaction-prompt override. Median over 3 runs each:

| mode | runs | compactions (median, range) | completed | summary has OBJECTIVE LOCK | has DO-NOT-REPEAT |
| --- | --- | --- | --- | --- | --- |
| baseline (default compaction) | 3 | 1 (1-2) | 3/3 | 0% | 0% |
| core lever only | 3 | 1 (1-1) | 3/3 | 100% | 100% |

The honest reading: at a budget where the task can finish, the lever does **not** reliably cut
the compaction count, and the small-task refactor completes either way. The robust,
reproducible difference is the **content of the compaction summary**. Every lever run
reproduced the objective verbatim, marked the NOTES read `[x]` done, and under
`COMPLETED INPUTS / DO-NOT-REPEAT` recorded `cat NOTES.md` already run plus a digest of its
content, with NEXT ACTION pointing straight at editing `calc.py`. No baseline run carried
either structure. That carry-forward is the anti-drift mechanism: even when compaction count
is identical, whether the summary preserves the original objective and completed work is what
decides if the resumed model advances or re-derives a narrowed goal.

#### Brutal-budget A/B

Live A/B through a Claude Opus 4.8 provider, deliberately brutal `40000`-token compaction
limit with a ~320KB `NOTES.md` (the case that breaks naive setups):

| run | compactions to finish | refactor completed |
| --- | --- | --- |
| throughline | 16 | yes, correct |
| default baseline | 27 | yes, eventually |
| throughline (2nd run) | 49+ | no; anti-loop fired but the edit never landed |

The decisive mechanism is visible in the rollout: every throughline compaction summary
carries a `COMPLETED INPUTS / DO-NOT-REPEAT` block that records "cat NOTES.md: already
read ... DO NOT re-read," and the resuming model acts on it ("summary says NOTES.md is
already read, so I'll skip it and go to edit"). The old failure of re-reading the large
file forever is gone, and throughline reaches the same correct result with fewer
compactions than the baseline.

Honest limit: at a pathologically tight budget the per-turn working set (resume summary +
tool schemas + reading the target file) can itself approach the limit, so completion is
timing-sensitive and high-variance. At a realistic budget (`120000`) the task completes
with zero compactions. Real Codex compacts near `300000`, where this is a non-issue.

## How it's wired

| Layer | Codex | Claude Code |
| --- | --- | --- |
| Objective card (SSOT) | `.throughline.md` on disk | `.throughline.md` on disk |
| Compaction-time state-lock | `experimental_compact_prompt_file` | `PreCompact` snapshot |
| Re-injection | `SessionStart` (startup/resume) + `UserPromptSubmit` | `SessionStart` (startup/resume/**compact**) + `UserPromptSubmit` |

## Layout

```
throughline/
  install.sh
  marketplace.json
  scripts/{verify_local,run_codex_compaction_trial}.py
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
