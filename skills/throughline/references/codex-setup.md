# Codex setup

## One command
```bash
python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/install.py --codex
```
This does everything:
- writes the injector handlers into `~/.codex/hooks.json` (preserving any other tools' hooks),
- adds `experimental_compact_prompt_file` (the compaction state-lock) and `hooks = "./hooks.json"`
  to `config.toml`, inserting them above the first `[table]` so they stay top-level keys,
- backs up `config.toml` to `config.toml.throughline.bak` before the first edit.

Re-running is idempotent: managed lines carry a `# throughline-managed` marker, so the
installer refreshes the path in place and never duplicates. If you already set
`experimental_compact_prompt_file` or `hooks` yourself, the installer keeps your value and
prints that it left it untouched.

## Why the two keys matter
`experimental_compact_prompt_file` overrides the summary prompt used at compaction, so every
compaction summary begins with OBJECTIVE LOCK, PROGRESS CHECKLIST, COMPLETED INPUTS /
DO-NOT-REPEAT, and NEXT ACTION. This is the only Codex control that influences what survives
an in-process compaction, so it is the highest-value line. `hooks = "./hooks.json"` is what
makes Codex load the injector at all.

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
- Uninstall: `python3 .../install.py --uninstall --codex` removes the managed config lines and
  our hook handlers, and preserves other tools' hooks and your own config keys.
