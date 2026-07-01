#!/usr/bin/env python3
"""Idempotent installer for throughline Codex hooks.

Wires throughline_hook.py so the objective card is re-injected on manual turns
and on resume/session start. The compaction-time state-lock is installed through
Codex's experimental_compact_prompt_file.

Usage:
  python3 install.py [--print]
  python3 install.py --uninstall

Re-running is safe: our entries are matched by a stable tag and replaced in place,
and other tools' hooks are preserved.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "throughline_hook.py")
# Pin the interpreter that ran the installer so the hook fires even when the
# hook runtime has no `python3` on PATH (Windows, minimal shells, pyenv shims).
PYTHON = sys.executable or "python3"
COMPACT_PROMPT = os.path.normpath(os.path.join(HERE, "..", "assets", "compact_prompt.md"))
TAG = "throughline"
MANAGED = "# throughline-managed"
BLOCK_START = "# >>> throughline (managed, do not edit) >>>"
BLOCK_END = "# <<< throughline <<<"

CODEX_HOME = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))

# Codex SessionStart has no `compact` matcher; resume is the key one for
# post-compaction recovery across a restart.
CODEX_EVENTS = {
    "SessionStart": ["startup", "resume"],
    "UserPromptSubmit": [None],
}


def _cmd():
    return f'"{PYTHON}" "{HOOK}"'


def _toml_escape(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _codex_hooks_block():
    """Inline [hooks.*] TOML that Codex actually accepts (HookEventsToml).

    Codex rejects `hooks = "./hooks.json"`; hooks must be inline tables. The
    compact-prompt override lives in the same managed block as a top-level key.
    """
    cmd = f'"{_toml_escape(PYTHON)}" "{_toml_escape(HOOK)}"'
    lines = [
        BLOCK_START,
        f'experimental_compact_prompt_file = "{_toml_escape(COMPACT_PROMPT)}"',
        "",
        "[hooks]",
        "[[hooks.UserPromptSubmit]]",
        "[[hooks.UserPromptSubmit.hooks]]",
        'type = "command"',
        f"command = {json.dumps(cmd)}",
    ]
    for matcher in ("startup", "resume"):
        lines += [
            "",
            "[[hooks.SessionStart]]",
            f'matcher = "{matcher}"',
            "[[hooks.SessionStart.hooks]]",
            'type = "command"',
            f"command = {json.dumps(cmd)}",
        ]
    lines.append(BLOCK_END)
    return "\n".join(lines)


def _load(path):
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as fh:
            try:
                return json.load(fh)
            except Exception:
                pass
    return {}


def _save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def _ours(handler):
    cmd = handler.get("command", "")
    return TAG in cmd or "throughline_hook.py" in cmd


def _build_matchers(events):
    out = {}
    for event, matchers in events.items():
        entries = []
        for m in matchers:
            entry = {"hooks": [{"type": "command", "command": _cmd()}]}
            if m is not None:
                entry["matcher"] = m
            entries.append(entry)
        out[event] = entries
    return out


def _merge(existing_hooks, ours, remove=False):
    hooks = dict(existing_hooks or {})
    for event, our_entries in ours.items():
        kept = [
            e for e in hooks.get(event, [])
            if not any(_ours(h) for h in e.get("hooks", []))
        ]
        hooks[event] = kept if remove else kept + our_entries
        if not hooks[event]:
            del hooks[event]
    return hooks


def _strip_managed_block(text):
    """Remove a previously written throughline block (and legacy managed lines)."""
    out, skipping = [], False
    for ln in text.splitlines():
        if ln.strip() == BLOCK_START:
            skipping = True
            continue
        if skipping:
            if ln.strip() == BLOCK_END:
                skipping = False
            continue
        if MANAGED in ln:  # legacy single-line keys from older installs
            continue
        out.append(ln)
    # drop trailing blank lines left behind
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def _patch_config_toml(remove=False):
    """Idempotently wire the Codex compact-prompt + inline hooks block.

    The block is bounded by sentinels so uninstall is exact, and is appended at
    end-of-file (inline [hooks.*] tables are valid there). A user's own
    experimental_compact_prompt_file outside the block is left untouched. A
    .throughline.bak backup is written before any change.
    """
    cfg = os.path.join(CODEX_HOME, "config.toml")
    notes = []

    original = ""
    if os.path.isfile(cfg):
        with open(cfg, "r", encoding="utf-8") as fh:
            original = fh.read()
    elif remove:
        return notes

    stripped = _strip_managed_block(original)

    if remove:
        new = stripped + ("\n" if stripped else "")
    else:
        user_has_own = (
            re.search(r"(?m)^\s*experimental_compact_prompt_file\s*=", stripped) is not None
        )
        if user_has_own:
            notes.append(
                "kept your existing experimental_compact_prompt_file; "
                "throughline's compaction state-lock is NOT active. Remove yours to enable it."
            )
        body = stripped.rstrip()
        new = (body + "\n\n" if body else "") + _codex_hooks_block() + "\n"

    if new == original:
        return notes

    if os.path.isfile(cfg):
        bak = cfg + ".throughline.bak"
        with open(bak, "w", encoding="utf-8") as fh:
            fh.write(original)
        notes.append(f"backed up config.toml -> {bak}")
    else:
        os.makedirs(os.path.dirname(cfg), exist_ok=True)

    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write(new)
    notes.append(
        "config.toml: removed throughline hooks block" if remove
        else "config.toml: wired inline hooks + compact prompt"
    )
    return notes


def install_codex(remove=False):
    # Clean up any legacy hooks.json from older installs (Codex never loaded it;
    # `hooks = "./hooks.json"` is rejected by config parsing).
    legacy = os.path.join(CODEX_HOME, "hooks.json")
    cfg_note = _patch_config_toml(remove=remove)
    cfg = os.path.join(CODEX_HOME, "config.toml")
    print(f"[codex] {'removed' if remove else 'installed'} -> {cfg}")
    if os.path.isfile(legacy):
        try:
            data = _load(legacy)
            data["hooks"] = _merge(data.get("hooks", {}), _build_matchers(CODEX_EVENTS), remove=True)
            if data.get("hooks"):
                _save(legacy, data)
            else:
                os.remove(legacy)
            cfg_note.append("removed legacy hooks.json (Codex loads inline config instead)")
        except Exception:
            pass
    for line in cfg_note:
        print(f"  {line}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--print", dest="dry", action="store_true",
                    help="print resulting hook entries, do not write")
    args = ap.parse_args()

    if args.dry:
        print(json.dumps({"codex": _build_matchers(CODEX_EVENTS)}, indent=2))
        return
    install_codex(remove=args.uninstall)


if __name__ == "__main__":
    main()
