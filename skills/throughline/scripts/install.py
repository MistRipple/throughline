#!/usr/bin/env python3
"""Idempotent installer for throughline hooks (Codex + Claude Code).

Wires throughline_hook.py so the objective card is re-injected on manual turns
and on resume/session start. Compaction-time state-lock is configured
separately (see references/) because the two tools differ there.

Usage:
  python3 install.py [--codex] [--claude] [--print]   # default: both
  python3 install.py --uninstall [--codex] [--claude]

Re-running is safe: our entries are matched by a stable tag and replaced in place,
and other tools' hooks are preserved.
"""
import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "throughline_hook.py")
COMPACT_PROMPT = os.path.normpath(os.path.join(HERE, "..", "assets", "compact_prompt.md"))
TAG = "throughline"
MANAGED = "# throughline-managed"

CODEX_HOME = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
CLAUDE_HOME = os.path.expanduser("~/.claude")

# Codex SessionStart has no `compact` matcher; resume is the key one for
# post-compaction recovery across a restart.
CODEX_EVENTS = {
    "SessionStart": ["startup", "resume"],
    "UserPromptSubmit": [None],
}
CLAUDE_EVENTS = {
    "SessionStart": ["startup", "resume", "compact"],
    "UserPromptSubmit": [None],
}


def _cmd():
    return f'python3 "{HOOK}"'


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


def _first_table_idx(lines):
    """Index of the first TOML table/array-of-tables header, else len(lines).

    Top-level keys must be inserted before this point; appending after a
    `[table]` header would silently reparent the key into that table.
    """
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("["):
            return i
    return len(lines)


def _toplevel_key_line(lines, key):
    """Return index of a top-level `key = ...` line, or None."""
    pat = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    for i in range(_first_table_idx(lines)):
        if pat.match(lines[i]):
            return i
    return None


def _patch_config_toml(remove=False):
    """Idempotently wire the two Codex top-level keys into config.toml.

    Manages exactly the lines we add, tagged with a trailing marker so uninstall
    is precise. Never clobbers a key the user already set themselves; writes a
    .throughline.bak backup before any change. Returns a list of note lines.
    """
    cfg = os.path.join(CODEX_HOME, "config.toml")
    notes = []
    desired = {
        "experimental_compact_prompt_file": f'"{COMPACT_PROMPT}"',
        "hooks": '"./hooks.json"',
    }

    lines = []
    if os.path.isfile(cfg):
        with open(cfg, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    elif remove:
        return notes

    original = list(lines)

    if remove:
        lines = [ln for ln in lines if MANAGED not in ln]
    else:
        to_insert = []
        for key, value in desired.items():
            managed_line = f"{key} = {value}  {MANAGED}"
            idx = _toplevel_key_line(lines, key)
            if idx is None:
                to_insert.append(managed_line)
            elif MANAGED in lines[idx]:
                lines[idx] = managed_line  # refresh path on re-run
            else:
                notes.append(
                    f"kept your existing `{key}` in config.toml; left it untouched."
                )
        if to_insert:
            at = _first_table_idx(lines)
            if at > 0 and lines[at - 1].strip():
                to_insert = [""] + to_insert
            lines[at:at] = to_insert

    if lines == original:
        return notes

    if os.path.isfile(cfg):
        bak = cfg + ".throughline.bak"
        with open(bak, "w", encoding="utf-8") as fh:
            fh.write("\n".join(original) + ("\n" if original else ""))
        notes.append(f"backed up config.toml -> {bak}")
    else:
        os.makedirs(os.path.dirname(cfg), exist_ok=True)

    with open(cfg, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    notes.append(
        "config.toml updated (removed throughline keys)" if remove
        else "config.toml wired (compact prompt + hooks)"
    )
    return notes


def install_codex(remove=False):
    path = os.path.join(CODEX_HOME, "hooks.json")
    data = _load(path)
    data["hooks"] = _merge(data.get("hooks", {}), _build_matchers(CODEX_EVENTS), remove)
    _save(path, data)
    cfg_note = _patch_config_toml(remove=remove)
    print(f"[codex] {'removed' if remove else 'installed'} -> {path}")
    for line in cfg_note:
        print(f"  {line}")


def install_claude(remove=False):
    path = os.path.join(CLAUDE_HOME, "settings.json")
    data = _load(path)
    data["hooks"] = _merge(data.get("hooks", {}), _build_matchers(CLAUDE_EVENTS), remove)
    _save(path, data)
    print(f"[claude] {'removed' if remove else 'installed'} -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codex", action="store_true")
    ap.add_argument("--claude", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--print", dest="dry", action="store_true",
                    help="print resulting hook entries, do not write")
    args = ap.parse_args()

    both = not (args.codex or args.claude)
    if args.dry:
        print(json.dumps({
            "codex": _build_matchers(CODEX_EVENTS),
            "claude": _build_matchers(CLAUDE_EVENTS),
        }, indent=2))
        return
    if args.codex or both:
        install_codex(remove=args.uninstall)
    if args.claude or both:
        install_claude(remove=args.uninstall)


if __name__ == "__main__":
    main()
