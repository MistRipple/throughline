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

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "throughline_hook.py")
TAG = "throughline"

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


def install_codex(remove=False):
    path = os.path.join(CODEX_HOME, "hooks.json")
    data = _load(path)
    data["hooks"] = _merge(data.get("hooks", {}), _build_matchers(CODEX_EVENTS), remove)
    _save(path, data)
    note = ""
    cfg = os.path.join(CODEX_HOME, "config.toml")
    if not remove and os.path.isfile(cfg):
        with open(cfg, "r", encoding="utf-8") as fh:
            body = fh.read()
        if "hooks =" not in body and 'hooks="' not in body:
            note = ('  NOTE: add `hooks = "./hooks.json"` to config.toml so Codex '
                    "loads it.")
    print(f"[codex] {'removed' if remove else 'installed'} -> {path}{note}")


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
