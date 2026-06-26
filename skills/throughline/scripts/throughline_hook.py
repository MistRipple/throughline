#!/usr/bin/env python3
"""throughline injector hook for Codex.

Reads a hook event JSON on stdin, finds the active throughline card for the
event's working directory, and emits it as additionalContext so the objective +
progress survive across manual turns and post-compaction resume.

Resolution order for the card:
  1. $THROUGHLINE_CARD (explicit path)
  2. nearest `.throughline.md` walking up from cwd to the git/fs root

Safe by design: any error -> emit nothing and exit 0 (never block the turn).
"""
import json
import os
import re
import sys

INJECT_CAP = 9000  # stay under the ~10k additionalContext limit


def find_card(start_dir):
    explicit = os.environ.get("THROUGHLINE_CARD")
    if explicit and os.path.isfile(explicit):
        return explicit
    d = os.path.abspath(start_dir or ".")
    while True:
        cand = os.path.join(d, ".throughline.md")
        if os.path.isfile(cand):
            return cand
        if os.path.isdir(os.path.join(d, ".git")):
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def _should_inject(text):
    """Skip stale cards. A card with status: done belongs to a finished task, and an
    unfilled template placeholder carries no real objective; injecting either would
    pollute the next task's context instead of anchoring it."""
    if re.search(r"(?im)^\s*status\s*:\s*done\b", text):
        return False
    m = re.search(r"(?im)^OBJECTIVE:\s*(.+?)\s*$", text)
    if m:
        obj = m.group(1).strip()
        if not obj or (obj.startswith("<") and obj.endswith(">")):
            return False
    return True


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        event = {}

    cwd = event.get("cwd") or event.get("workdir") or os.getcwd()
    event_name = event.get("hookEventName") or event.get("hook_event_name") or "UserPromptSubmit"

    card = find_card(cwd)
    if not card:
        sys.exit(0)

    text = _read(card)
    if not text:
        sys.exit(0)

    if not _should_inject(text):
        sys.exit(0)

    if len(text) > INJECT_CAP:
        text = text[:INJECT_CAP] + "\n<!-- truncated to injection cap -->"

    context = (
        "[throughline] Active objective card restored from disk (SSOT). "
        "Honor the OBJECTIVE LOCK verbatim; do not narrow the objective to "
        "'harden/validate/clean up existing code'. Re-read and update this card "
        "at each milestone.\n\n"
        f"Card: {card}\n\n{text}"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        }
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
