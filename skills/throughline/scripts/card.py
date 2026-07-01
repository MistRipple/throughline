#!/usr/bin/env python3
"""throughline card lifecycle: `new` a task line (archives the old), `resume` the current one.

A new task gets a NEW card. The objective card is per-task: its OBJECTIVE LOCK is
the verbatim original objective for that one task, so reusing a card across tasks
would inject a stale objective into the next task and cause the exact drift this
skill exists to stop.

Two verbs carry the intent, so no flags or prompts are needed to disambiguate:
  - `new`    opens a fresh objective line and archives any existing card. Whether the
             old card was active, done, or a placeholder, it is archived (never
             deleted), so even a mistaken `new` is fully recoverable.
  - `resume` keeps working the current card: a done card is reactivated, an active
             one is confirmed as-is. It never archives and never overwrites. This is
             the safe default after an interruption, resume, or context compaction.
`init` and `reopen` remain as aliases for `new` and `resume`. The disk card is
gitignored and git keeps no history of it, so the archive move is its only backup.

Usage:
  python3 card.py new --objective "..." [--task-type feature] [--task-id slug] [--card PATH]
  python3 card.py resume [--card PATH]   # keep the current objective (reactivates if done)
  python3 card.py done [--card PATH]     # mark the current task complete (hook goes silent)
  python3 card.py check [--strict] [--card PATH]   # enforce size/section budgets
  # aliases: `init` == `new`, `reopen` == `resume`

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


def _resolve_card(start_dir=None):
    """Resolve the card path the same way the hook does, so `init` writes exactly
    where the injector will later read. Walk up from cwd to the git/fs root: reuse
    an existing `.throughline.md` if found, otherwise anchor a new one at the git
    root (falling back to cwd when there is no repo)."""
    d = os.path.abspath(start_dir or os.getcwd())
    git_root = None
    while True:
        cand = os.path.join(d, ".throughline.md")
        if os.path.isfile(cand):
            return cand
        if os.path.isdir(os.path.join(d, ".git")):
            git_root = d
            break
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    base = git_root or os.path.abspath(start_dir or os.getcwd())
    return os.path.join(base, ".throughline.md")


def _default_card():
    explicit = os.environ.get("THROUGHLINE_CARD")
    if explicit:
        return os.path.abspath(explicit)
    return _resolve_card()


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


def cmd_new(args):
    """Open a NEW objective line. The verb says it plainly, so there is no prompt and
    no flag: any existing card is archived (not deleted, so a mistaken `new` is fully
    recoverable from the archive) and the new objective is locked in. Use `resume` to
    keep working the current card instead."""
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
    print(f"[card] new task locked at {card} (task_id={task_id})")
    if archived:
        print(f"  archived previous card -> {archived}")
    return 0


def _touch_updated(text):
    """Refresh meta.updated to now so the archive timestamp stays chronological."""
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    text, n = re.subn(r"(?im)^(\s*updated\s*:\s*).*$",
                      lambda m: m.group(1) + now, text, count=1)
    return text


def _set_status(card, status):
    """Set meta.status on the card (inserting it if the card predates the field) and
    refresh meta.updated so a later archive is stamped with the real change time."""
    text = _read(card)
    if re.search(r"(?im)^\s*status\s*:", text):
        text = re.sub(r"(?im)^(\s*status\s*:\s*).*$",
                      lambda m: m.group(1) + status, text, count=1)
    else:
        text = re.sub(r"(?m)^(\s*size_budget_bytes:.*)$",
                      lambda m: m.group(1) + f"\n  status: {status}", text, count=1)
    text = _touch_updated(text)
    _write(card, text)


def cmd_done(args):
    card = os.path.abspath(args.card) if args.card else _default_card()
    if not os.path.isfile(card):
        print(f"error: no card at {card}", file=sys.stderr)
        return 2
    _set_status(card, "done")
    print(f"[card] marked done {card} (hook will stay silent until a new task card)")
    return 0


def cmd_resume(args):
    """Keep working the CURRENT objective line - the counterpart to `new`. It never
    archives and never overwrites: a done card is reactivated, an already-active card
    is confirmed as-is. This is the safe default when you come back to the same task
    after an interruption, resume, or context compaction."""
    card = os.path.abspath(args.card) if args.card else _default_card()
    if not os.path.isfile(card):
        print(f"error: no card at {card} - nothing to resume; run `new` to open one", file=sys.stderr)
        return 2
    text = _read(card)
    obj = _meta_value(text, "OBJECTIVE")
    if not obj or (obj.startswith("<") and obj.endswith(">")):
        print(f"error: {card} has no real objective yet; run `new` to lock one", file=sys.stderr)
        return 2
    was_done = bool(re.search(r"(?im)^\s*status\s*:\s*done\b", text))
    if was_done:
        _set_status(card, "active")
        print(f"[card] resumed {card} (reactivated; hook injects this card again)")
    else:
        print(f"[card] resuming {card} (already active)")
    print(f"  objective: {obj}")
    return 0


SECTION_CAPS = [
    ("COMPLETED INPUTS / DO-NOT-REPEAT", 12),
    ("DECISIONS", 10),
    ("PROGRESS CHECKLIST", 20),
]


def _section_body(text, title):
    """Return the lines between a `## === <title> ... ===` header and the next
    `## ` header (or EOF). Matching is lenient about trailing text in the header."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("## ") and title in ln:
            start = i + 1
            break
    if start is None:
        return None
    body = []
    for ln in lines[start:]:
        if ln.lstrip().startswith("## "):
            break
        body.append(ln)
    return body


def _count_items(body):
    """Count real list items, ignoring HTML comments and unfilled <placeholder> stubs."""
    n = 0
    in_comment = False
    for ln in body:
        stripped = ln.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            if "-->" not in stripped:
                in_comment = True
            continue
        if not stripped.startswith("-"):
            continue
        item = stripped.lstrip("-").strip()
        item = re.sub(r"^\[.\]\s*", "", item)  # drop checklist marker
        if not item or (item.startswith("<") and item.endswith(">")):
            continue
        n += 1
    return n


def _budget_bytes(text):
    v = _meta_value(text, "size_budget_bytes")
    if v:
        m = re.match(r"\s*(\d+)", v)
        if m:
            return int(m.group(1))
    return None


def cmd_check(args):
    card = os.path.abspath(args.card) if args.card else _default_card()
    if not os.path.isfile(card):
        print(f"error: no card at {card}", file=sys.stderr)
        return 2
    text = _read(card)
    warnings = []

    size = len(text.encode("utf-8"))
    budget = _budget_bytes(text)
    if budget is not None and size > budget:
        warnings.append(f"size {size}B exceeds size_budget_bytes {budget}B; trim oldest entries")

    for title, cap in SECTION_CAPS:
        body = _section_body(text, title)
        if body is None:
            continue
        count = _count_items(body)
        if count > cap:
            warnings.append(f"section '{title}' has {count} items; cap is {cap}")

    obj = _meta_value(text, "OBJECTIVE")
    if not obj or (obj.startswith("<") and obj.endswith(">")):
        warnings.append("OBJECTIVE is empty or still an unfilled <placeholder>")

    if not warnings:
        print(f"[card] ok {card} ({size}B" + (f"/{budget}B budget)" if budget else ")"))
        return 0
    print(f"[card] {len(warnings)} warning(s) for {card}:", file=sys.stderr)
    for w in warnings:
        print(f"  - {w}", file=sys.stderr)
    return 1 if args.strict else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="throughline card lifecycle")
    sub = ap.add_subparsers(dest="command", required=True)

    # `new` opens a fresh objective line (archives any existing card); `resume` keeps
    # the current one. Two verbs carry the intent, so no flag or prompt is needed.
    # `init`/`reopen` remain as aliases for existing docs and muscle memory.
    p_new = sub.add_parser("new", aliases=["init"],
                           help="open a NEW objective line, archiving any existing card")
    p_new.add_argument("--objective", required=True, help="verbatim original objective")
    p_new.add_argument("--task-type", default="feature",
                       help="refactor | feature | bugfix | migration | investigation")
    p_new.add_argument("--task-id", default=None, help="slug; defaults to one derived from the objective")
    p_new.add_argument("--card", default=None, help="card path; defaults to the resolved root card")
    p_new.set_defaults(func=cmd_new)

    p_resume = sub.add_parser("resume", aliases=["reopen"],
                              help="keep working the CURRENT card (reactivates it if done)")
    p_resume.add_argument("--card", default=None, help="card path; defaults to the resolved root card")
    p_resume.set_defaults(func=cmd_resume)

    p_done = sub.add_parser("done", help="mark the current card complete")
    p_done.add_argument("--card", default=None, help="card path; defaults to the resolved root card")
    p_done.set_defaults(func=cmd_done)

    p_check = sub.add_parser("check", help="warn when the card exceeds its size/section budgets")
    p_check.add_argument("--card", default=None, help="card path; defaults to the resolved root card")
    p_check.add_argument("--strict", action="store_true", help="exit non-zero when any budget is exceeded")
    p_check.set_defaults(func=cmd_check)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
