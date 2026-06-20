# Claude Code setup

## 1. Injector hook (manual turns + resume + post-compact)
```bash
python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/install.py --claude
```
Writes `~/.claude/settings.json`. Claude's `SessionStart` supports a `compact` matcher, so
the hook re-injects the card right after compaction completes, plus on startup, resume, and
every `UserPromptSubmit`. Same `throughline_hook.py`, same `additionalContext` schema as
Codex.

## 2. What Claude can and cannot do at compaction
Claude has no equivalent of Codex's `experimental_compact_prompt_file`. There is no supported
way to force the compaction summary to carry an OBJECTIVE LOCK / DO-NOT-REPEAT block. The
`PreCompact` hook fires before compaction, but its output is additive context only; it cannot
rewrite or steer the summary the model produces. So on Claude the in-process compaction
summary itself is not under our control.

throughline therefore protects Claude from the *outside* of the summary, in two moves the
installer wires automatically:

1. `PreCompact` snapshot. Right before compaction, the hook copies `.throughline.md` to
   `.throughline.precompact.bak`. The objective and COMPLETED INPUTS / DO-NOT-REPEAT survive
   on disk even if the summary loses them. Overwrite-in-place, so the backup never grows.
2. `SessionStart:compact` re-injection. Immediately after compaction, the hook feeds the card
   back into context as `additionalContext`, restoring the objective and progress the summary
   may have dropped.

If the live card itself was degraded during compaction (its `OBJECTIVE` anchor is gone), the
re-injection hook detects that, restores `.throughline.md` from `.throughline.precompact.bak`,
and injects it flagged as "RESTORED from the pre-compaction snapshot" so the resumed model
trusts it over the summary. A healthy live card is never overwritten by the snapshot.

Practical consequence: on Claude the disk card carries more of the load than on Codex, and
the restore happens *after* the summary rather than *inside* it. Update the card at every
milestone, especially COMPLETED INPUTS / DO-NOT-REPEAT, so the post-compact re-injection has
current state to restore.

## 3. Verify
```bash
echo '{"cwd":"'"$PWD"'","hook_event_name":"UserPromptSubmit"}' \
  | python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/throughline_hook.py
```
Expect a JSON object with `additionalContext` when a `.throughline.md` exists.

## Notes
- Schema is identical to Codex (`hookSpecificOutput.additionalContext`); one injector serves
  both tools.
- The injector is also the snapshotter: on `PreCompact` it writes the backup and emits no
  context; on every other event it injects the card.
- Uninstall: `python3 .../install.py --uninstall --claude`.
