#!/usr/bin/env python3
"""throughline injector hook (Codex + Claude compatible).

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
import shutil
import sys

INJECT_CAP = 9000  # stay under the ~10k additionalContext limit
SNAPSHOT_NAME = ".throughline.precompact.bak"
# A healthy card must carry the objective anchor. If the live card lost it (a degraded
# post-compaction write), we treat the card as corrupted and fall back to the snapshot.
HEALTH_ANCHOR = "OBJECTIVE"


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


def _healthy(text):
    return bool(text) and HEALTH_ANCHOR in text


def main():
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        event = {}

    cwd = event.get("cwd") or event.get("workdir") or os.getcwd()
    event_name = (
        event.get("hookEventName")
        or event.get("hook_event_name")
        or "UserPromptSubmit"
    )

    card = find_card(cwd)
    if not card:
        sys.exit(0)

    # PreCompact (Claude) cannot steer the summary, and additionalContext at this event is
    # not reliably injected. The one useful, bounded action is to snapshot the card so the
    # objective + DO-NOT-REPEAT survive even if the card is later corrupted. Overwrite in
    # place so the backup never grows.
    if event_name == "PreCompact":
        try:
            backup = os.path.join(os.path.dirname(card), SNAPSHOT_NAME)
            shutil.copyfile(card, backup)
        except Exception:
            pass
        sys.exit(0)

    text = _read(card)
    restored = False
    # Recovery: if the live card is missing its objective anchor (degraded during compaction)
    # but a healthy pre-compaction snapshot exists, restore from it and inject that instead.
    if not _healthy(text):
        backup = os.path.join(os.path.dirname(card), SNAPSHOT_NAME)
        snap = _read(backup)
        if _healthy(snap):
            try:
                shutil.copyfile(backup, card)
            except Exception:
                pass
            text = snap
            restored = True
    if not text:
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
    if restored:
        context = (
            "[throughline] The live card was degraded after compaction and has been "
            "RESTORED from the pre-compaction snapshot. Trust the OBJECTIVE LOCK and "
            "PROGRESS below as the source of truth.\n\n" + context
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
