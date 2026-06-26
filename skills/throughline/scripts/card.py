#!/usr/bin/env python3
"""throughline card lifecycle: start a fresh task card, archive the previous one.

A new task gets a NEW card. The objective card is per-task: its OBJECTIVE LOCK is
the verbatim original objective for that one task, so reusing a card across tasks
would inject a stale objective into the next task and cause the exact drift this
skill exists to stop.

`init` archives the existing root card (if any) before writing the new one, so no
in-progress state is silently overwritten. The disk card is gitignored and git keeps
no history of it, so this move is the only backup it gets.

Usage:
  python3 card.py init --objective "..." [--task-type feature] [--task-id slug] [--card PATH]
  python3 card.py done [--card PATH]     # mark the current task complete (hook goes silent)
  python3 card.py reopen [--card PATH]   # reactivate a done card (reverse of done)

Archive location: <card-dir>/.throughline/archive/<task_id>_<timestamp>.md
"""
import argparse
import datetime as _dt
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.normpath(os.path.join(HERE, "..", "assets", "throughline-card.template.md"))


def _default_card():
    explicit = os.environ.get("THROUGHLINE_CARD")
    if explicit:
        return os.path.abspath(explicit)
    return os.path.abspath(os.path.join(os.getcwd(), ".throughline.md"))


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write(path, text):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _meta_value(text, key):
    m = re.search(rf"(?im)^\s*{re.escape(key)}\s*:\s*(.+?)\s*$", text)
    return m.group(1).strip() if m else None


def _slugify(text, fallback="task"):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = "-".join(slug.split("-")[:6])
    return slug or fallback


def _archive(card_path):
    """Move an existing root card into the gitignored archive. Returns the dest or None."""
    if not os.path.isfile(card_path):
        return None
    text = _read(card_path)
    task_id = _meta_value(text, "task_id") or "task"
    if task_id.startswith("<"):
        task_id = "task"
    stamp = (_meta_value(text, "updated") or "").strip()
    stamp = re.sub(r"[^0-9]+", "", stamp) or _dt.datetime.now().strftime("%Y%m%d%H%M%S")
    dest_dir = os.path.join(os.path.dirname(card_path) or ".", ".throughline", "archive")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{task_id}_{stamp}.md")
    n = 1
    while os.path.exists(dest):
        dest = os.path.join(dest_dir, f"{task_id}_{stamp}_{n}.md")
        n += 1
    shutil.move(card_path, dest)
    return dest


def _fill_template(objective, task_type, task_id):
    text = _read(TEMPLATE)
    today = _dt.date.today().isoformat()
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    # Use callable replacements so values like the objective are written verbatim:
    # a literal "\\g<1>" or "\\1" in user text must never be read as a backreference.
    repl = [
        (r"(?m)^(\s*task_id:\s*).*$", task_id),
        (r"(?m)^(\s*created:\s*).*$", today),
        (r"(?m)^(\s*updated:\s*).*$", now),
        (r"(?m)^(\s*status:\s*).*$", "active"),
        (r"(?m)^(OBJECTIVE:\s*).*$", objective),
        (r"(?m)^(TASK TYPE:\s*).*$", task_type),
    ]
    for pat, value in repl:
        text, n = re.subn(pat, lambda m, v=value: m.group(1) + v, text, count=1)
        if n == 0:
            raise ValueError(
                f"template {TEMPLATE} is missing a line matching {pat!r}; "
                "cannot fill the card safely"
            )
    # Defense in depth: confirm the verbatim objective actually landed.
    if _meta_value(text, "OBJECTIVE") != objective:
        raise ValueError("objective was not written verbatim into the card")
    if _meta_value(text, "task_id") != task_id:
        raise ValueError("task_id was not written into the card")
    return text


def cmd_init(args):
    card = os.path.abspath(args.card) if args.card else _default_card()
    objective = args.objective.strip()
    if not objective:
        print("error: --objective must not be empty", file=sys.stderr)
        return 2
    task_id = args.task_id or _slugify(objective)
    try:
        filled = _fill_template(objective, args.task_type, task_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    archived = _archive(card)
    _write(card, filled)
    print(f"[card] created {card} (task_id={task_id})")
    if archived:
        print(f"  archived previous card -> {archived}")
    return 0


def _set_status(card, status):
    """Set meta.status on the card, inserting the field if the card predates it."""
    text = _read(card)
    if re.search(r"(?im)^\s*status\s*:", text):
        text = re.sub(r"(?im)^(\s*status\s*:\s*).*$",
                      lambda m: m.group(1) + status, text, count=1)
    else:
        text = re.sub(r"(?m)^(\s*size_budget_bytes:.*)$",
                      lambda m: m.group(1) + f"\n  status: {status}", text, count=1)
    _write(card, text)


def cmd_done(args):
    card = os.path.abspath(args.card) if args.card else _default_card()
    if not os.path.isfile(card):
        print(f"error: no card at {card}", file=sys.stderr)
        return 2
    _set_status(card, "done")
    print(f"[card] marked done {card} (hook will stay silent until a new task card)")
    return 0


def cmd_reopen(args):
    card = os.path.abspath(args.card) if args.card else _default_card()
    if not os.path.isfile(card):
        print(f"error: no card at {card}", file=sys.stderr)
        return 2
    _set_status(card, "active")
    print(f"[card] reopened {card} (status=active; hook injects this card again)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="throughline card lifecycle")
    sub = ap.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="start a new task card, archiving any existing one")
    p_init.add_argument("--objective", required=True, help="verbatim original objective")
    p_init.add_argument("--task-type", default="feature",
                        help="refactor | feature | bugfix | migration | investigation")
    p_init.add_argument("--task-id", default=None, help="slug; defaults to one derived from the objective")
    p_init.add_argument("--card", default=None, help="card path; defaults to ./.throughline.md")
    p_init.set_defaults(func=cmd_init)

    p_done = sub.add_parser("done", help="mark the current card complete")
    p_done.add_argument("--card", default=None, help="card path; defaults to ./.throughline.md")
    p_done.set_defaults(func=cmd_done)

    p_reopen = sub.add_parser("reopen", help="reactivate a done card (reverse of done)")
    p_reopen.add_argument("--card", default=None, help="card path; defaults to ./.throughline.md")
    p_reopen.set_defaults(func=cmd_reopen)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
