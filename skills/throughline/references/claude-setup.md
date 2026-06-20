# Claude Code setup

## 1. Injector hook (manual turns + resume + post-compact)
```bash
python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/install.py --claude
```
Writes `~/.claude/settings.json`. Claude's `SessionStart` supports a `compact` matcher, so
the hook re-injects the card right after compaction completes, plus on startup, resume, and
every `UserPromptSubmit`. Same `throughline_hook.py`, same `additionalContext` schema as
Codex.

## 2. Compaction-time snapshot (PreCompact)
Claude cannot override the compaction summary prompt the way Codex can. What it offers is
`PreCompact`, which fires before compaction. Use it to snapshot the objective card so nothing
is lost even if the summary degrades; the `SessionStart:compact` hook then re-injects after.

Practical consequence: on Claude the disk card carries more of the load, because no verbatim
state-lock is injected into the summary itself. Re-read and update the card at every
milestone, especially COMPLETED INPUTS / DO-NOT-REPEAT, and rely on the `compact` matcher to
restore it immediately afterward.

## 3. Verify
```bash
echo '{"cwd":"'"$PWD"'","hook_event_name":"UserPromptSubmit"}' \
  | python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/throughline_hook.py
```
Expect a JSON object with `additionalContext` when a `.throughline.md` exists.

## Notes
- Schema is identical to Codex (`hookSpecificOutput.additionalContext`); one injector serves
  both tools.
- Uninstall: `python3 .../install.py --uninstall --claude`.
