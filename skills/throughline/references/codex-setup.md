# Codex setup

## 1. Compaction-time state-lock (highest value on Codex)
Codex lets you override the summary prompt used at compaction. Point it at the shipped asset
so every compaction summary begins with OBJECTIVE LOCK, PROGRESS CHECKLIST, COMPLETED
INPUTS / DO-NOT-REPEAT, and NEXT ACTION.

In `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`):

```toml
experimental_compact_prompt_file = "/ABSOLUTE/PATH/throughline/skills/throughline/assets/compact_prompt.md"
```

This is the only Codex control that influences what survives an in-context compaction, so it
is the most important line to add. Use the absolute path where you cloned the repo. The
completed-inputs section is the key guard against repeated large-file reads after compaction.

## 2. Injector hook (manual turns + resume)
```bash
python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/install.py --codex
```
It writes `~/.codex/hooks.json`. Codex only loads that file if `config.toml` references it:

```toml
hooks = "./hooks.json"
```
The installer prints a NOTE reminding you when the line is missing. Codex's `SessionStart`
has matchers `startup` / `resume` / `clear` (no `compact`), so the hook covers fresh starts,
resume-after-restart, and every manual `UserPromptSubmit`. It does NOT fire on in-process
compaction; that gap is exactly why layer 1 exists.

## 3. Verify
```bash
echo '{"cwd":"'"$PWD"'","hookEventName":"UserPromptSubmit"}' \
  | python3 /ABSOLUTE/PATH/throughline/skills/throughline/scripts/throughline_hook.py
```
With a `.throughline.md` in the repo you should see a JSON object containing
`additionalContext`. With no card it prints nothing and exits 0.

## Notes
- Hook event names are PascalCase; handler shape is `{"type":"command","command":"..."}`.
- `additionalContext` injection is capped near 10 KB; keep the card under its size budget.
- Uninstall: `python3 .../install.py --uninstall --codex` (preserves other tools' hooks).
