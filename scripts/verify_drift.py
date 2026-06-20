#!/usr/bin/env python3
"""Live Codex anti-drift verification across single-turn, multi-turn, and goal modes.

For each run it builds a workspace whose objective is to BUILD a new feature, salted
with heavy "harden the existing code" noise, forces compaction with a tight budget,
then parses EVERY compaction summary and reports:
  - drift: summaries that narrowed the objective to "harden/clean up existing code"
  - kept: summaries still naming the build target
  - lock: summaries carrying the OBJECTIVE LOCK header
  - card token overhead (chars/≈tokens of injected card vs a hard budget)

Real Codex only; isolates CODEX_HOME so your real config is never touched.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "skills" / "throughline" / "scripts" / "install.py"

BUILD_OBJECTIVE = (
    "Build a NEW email notification feature: add a Notifier class in notify.py that sends a "
    "templated email when an order ships, and wire it into ship_order()."
)
NARROW_PATTERNS = [
    "objective: harden", "objective: clean up the existing", "narrow the objective to harden",
    "tighten the existing code as the objective", "objective is now to harden",
    "focus on hardening the existing", "goal: harden the existing",
]
BUILD_TOKENS = ["notifier", "notification", "email"]


def card_text(goal_mode):
    head = "# THROUGHLINE\nmeta:\n  task_id: notify-feature\n  size_budget_bytes: 8000\n\n"
    if goal_mode:
        lock = (
            "## === OBJECTIVE LOCK (verbatim) ===\n"
            f"GOAL: {BUILD_OBJECTIVE}\n"
            "TOKEN BUDGET: 200000\n"
            "TASK TYPE: feature\n\n"
        )
    else:
        lock = (
            "## === OBJECTIVE LOCK (verbatim) ===\n"
            f"OBJECTIVE: {BUILD_OBJECTIVE}\n"
            "TASK TYPE: feature\n\n"
        )
    rest = (
        "## === OUT OF SCOPE ===\n- Hardening unrelated existing modules\n\n"
        "## === PROGRESS CHECKLIST ===\n"
        "- [x] Read legacy NOTES.md once\n"
        "- [ ] Add Notifier class in notify.py\n"
        "- [ ] Call Notifier from ship_order()\n"
        "- [ ] Verify with python3 notify.py demo\n\n"
        "## === NEXT ACTION ===\nCreate the Notifier class in notify.py.\n\n"
        "## === COMPLETED INPUTS / DO-NOT-REPEAT ===\n"
        "- cat NOTES.md | 1500 lines of legacy hardening tickets | already read; do NOT re-read\n"
    )
    return head + lock + rest


def build_workspace(work, goal_mode, notes_lines):
    work.mkdir(parents=True, exist_ok=True)
    (work / ".throughline.md").write_text(card_text(goal_mode), encoding="utf-8")
    (work / "notify.py").write_text(
        "def ship_order(order):\n    # TODO: notify customer\n    return True\n", encoding="utf-8"
    )
    noise = ["# Legacy Hardening Ledger", ""]
    for i in range(notes_lines):
        noise.append(
            f"- TICKET HARD-{i:04d}: harden the existing parser, validate current inputs, "
            f"tighten legacy error handling, clean up the existing module {i}"
        )
    (work / "NOTES.md").write_text("\n".join(noise) + "\n", encoding="utf-8")


def copy_home(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    if (src / "auth.json").exists():
        shutil.copy2(src / "auth.json", dst / "auth.json")
    text = (src / "config.toml").read_text(encoding="utf-8")
    text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("service_tier")) + "\n"
    (dst / "config.toml").write_text(text, encoding="utf-8")


def latest_rollout(home):
    files = sorted(home.glob("sessions/**/rollout-*.jsonl"))
    return files[-1] if files else None


def analyze(rollout):
    comps = []
    inj_chars = []
    for line in rollout.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "compacted":
            comps.append(item["payload"]["message"])
        # capture injected card size from hook output if present in the transcript
        blob = json.dumps(item)
        if "[throughline]" in blob and "OBJECTIVE" in blob:
            inj_chars.append(len(blob))
    drift = sum(1 for s in comps if any(p in s.lower() for p in NARROW_PATTERNS))
    kept = sum(1 for s in comps if any(w in s.lower() for w in BUILD_TOKENS))
    lock = sum(1 for s in comps if "objective lock" in s.lower())
    return {
        "compactions": len(comps),
        "drift": drift,
        "kept_build_target": kept,
        "objective_lock": lock,
    }


def analyze_many(rollouts):
    agg = {"compactions": 0, "drift": 0, "kept_build_target": 0, "objective_lock": 0}
    for r in rollouts:
        one = analyze(r)
        for k in agg:
            agg[k] += one[k]
    return agg


def session_id_of(rollout):
    for line in rollout.read_text(errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "session_meta":
            return item.get("payload", {}).get("id")
    return None


def session_rollouts(home, session_id):
    files = sorted(home.glob("sessions/**/rollout-*.jsonl"))
    if not session_id:
        return files[-1:] if files else []
    return [f for f in files if session_id_of(f) == session_id] or (files[-1:] if files else [])


def _spawn(cmd, work, env, logpath, timeout):
    with open(logpath, "w") as out:
        proc = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.DEVNULL)
        start = time.time()
        while proc.poll() is None and time.time() - start < timeout:
            time.sleep(5)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


# follow-up turns for multi mode: each keeps the BUILD objective and adds load,
# while explicitly re-tempting the agent toward the existing-hardening noise.
RESUME_TURNS = [
    "Continue the SAME objective from .throughline.md. Add an SMS fallback path inside the "
    "Notifier and keep the email feature as the goal. Do NOT re-read NOTES.md.",
    "Keep going on the SAME build objective. Add a demo block at the bottom of notify.py that "
    "constructs a Notifier and prints the email it would send, then finish wiring ship_order(). "
    "Do NOT pivot to hardening NOTES.md tickets.",
]


def run_once(args, mode, idx):
    base = Path(tempfile.mkdtemp(prefix=f"tl-drift-{mode}-{idx}-"))
    home = base / ".codex"
    work = base / "work"
    copy_home(Path(args.codex_home), home)
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    subprocess.run([sys.executable, str(INSTALL), "--codex"], env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    build_workspace(work, goal_mode=(mode == "goal"), notes_lines=args.notes_lines)

    prompt = (
        "Work the task in .throughline.md. Follow the OBJECTIVE LOCK exactly. Do NOT re-read "
        "NOTES.md (COMPLETED INPUTS covers it). Implement the feature in notify.py and run "
        "python3 notify.py demo when done."
    )
    common = [
        "-c", f"model_auto_compact_token_limit={args.token_limit}",
        "-c", 'model_reasoning_effort="low"',
    ]
    start_cmd = [
        "codex", "exec", "--dangerously-bypass-approvals-and-sandbox", "--json",
        "-C", str(work),
    ] + common + [prompt]
    _spawn(start_cmd, work, env, base / "run.jsonl", args.timeout)

    first = latest_rollout(home)
    session_id = session_id_of(first) if first else None

    if mode == "multi":
        for t in range(args.multi_turns):
            follow = RESUME_TURNS[t % len(RESUME_TURNS)]
            resume_cmd = [
                "codex", "exec", "resume",
                "--dangerously-bypass-approvals-and-sandbox", "--json",
                "-C", str(work),
            ] + common + ["--last", follow]
            _spawn(resume_cmd, work, env, base / f"resume-{t}.jsonl", args.timeout)

    rollouts = session_rollouts(home, session_id)
    res = {"mode": mode, "idx": idx, "root": str(base)}
    if rollouts:
        res.update(analyze_many(rollouts))
        res["rollouts"] = len(rollouts)
    # card overhead, measured directly from the injected card file
    card = (work / ".throughline.md").read_text(encoding="utf-8")
    res["card_bytes"] = len(card)
    res["card_tokens_est"] = len(card) // 4
    if not args.keep:
        shutil.rmtree(base, ignore_errors=True)
        res["root"] = "(removed)"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codex-home", default=os.path.expanduser("~/.codex"))
    ap.add_argument("--modes", default="single,multi,goal", help="comma list: single,multi,goal")
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--token-limit", type=int, default=22000)
    ap.add_argument("--notes-lines", type=int, default=1500)
    ap.add_argument("--multi-turns", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    results = []
    for mode in modes:
        for i in range(args.repeat):
            print(f"# {mode} run {i + 1}/{args.repeat}", file=sys.stderr, flush=True)
            results.append(run_once(args, mode, i))

    print(json.dumps(results, indent=2))
    print()
    # aggregate: the headline number is total drift across ALL compactions
    hdr = f"{'mode':<8}{'runs':>5}{'compactions':>13}{'DRIFT':>7}{'kept':>6}{'lock':>6}{'card_tok':>10}"
    print(hdr)
    print("-" * len(hdr))
    for mode in modes:
        rs = [r for r in results if r["mode"] == mode]
        comp = sum(r.get("compactions", 0) for r in rs)
        drift = sum(r.get("drift", 0) for r in rs)
        kept = sum(r.get("kept_build_target", 0) for r in rs)
        lock = sum(r.get("objective_lock", 0) for r in rs)
        ctok = max((r.get("card_tokens_est", 0) for r in rs), default=0)
        print(f"{mode:<8}{len(rs):>5}{comp:>13}{drift:>7}{kept:>6}{lock:>6}{ctok:>10}")


if __name__ == "__main__":
    main()
