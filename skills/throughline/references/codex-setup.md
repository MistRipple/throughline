# Codex setup

## One command
```bash
python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/install.py
```
This does everything:
- writes a single managed block to `config.toml`, bounded by
  `# >>> throughline ... >>>` / `# <<< throughline <<<` sentinels, containing the
  `experimental_compact_prompt_file` state-lock plus the **inline** `[hooks.*]` tables
  (`UserPromptSubmit` and `SessionStart` startup/resume) that point at the injector,
- backs up `config.toml` to `config.toml.throughline.bak` before the first edit,
- removes any stray legacy `hooks.json` entries from older installs.

Re-running is idempotent: the whole block is replaced in place, never duplicated. If you
already set `experimental_compact_prompt_file` yourself outside the block, the installer keeps
your value and prints that the state-lock is not active until you remove yours.

Codex requires inline hook tables. `hooks = "./hooks.json"` is **rejected** by config parsing
(`expected struct HookEventsToml`) and would stop Codex from starting, so throughline never
writes that form.

## Why the two keys matter
`experimental_compact_prompt_file` overrides the summary prompt used at compaction, so every
compaction summary begins with OBJECTIVE LOCK, PROGRESS CHECKLIST, COMPLETED INPUTS /
DO-NOT-REPEAT, and NEXT ACTION. This is the only Codex control that influences what survives
an in-process compaction, so it is the highest-value line. The inline `[hooks.*]` tables are
what make Codex load the injector at all.

Codex's `SessionStart` has matchers `startup` / `resume` / `clear` (no `compact`), so the
hook covers fresh starts, resume-after-restart, and every manual `UserPromptSubmit`. It does
NOT fire on in-process compaction; that gap is exactly why the compact prompt override exists.

## Verify
```bash
echo '{"cwd":"'"$PWD"'","hookEventName":"UserPromptSubmit"}' \
  | python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/throughline_hook.py
```
With a `.throughline.md` in the repo you should see a JSON object containing
`additionalContext`. With no card it prints nothing and exits 0.

## Notes
- Hook event names are PascalCase; handler shape is `{"type":"command","command":"..."}`.
- `additionalContext` injection is capped near 10 KB; keep the card under its size budget.
- Uninstall: `python3 .../install.py --uninstall` removes the managed config lines and
  our hook handlers, and preserves other tools' hooks and your own config keys.
