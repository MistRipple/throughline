#!/usr/bin/env python3
"""Run a live Codex compaction trial for throughline.

This script is intentionally optional because it calls a real model. It creates an
isolated CODEX_HOME, copies auth/config from an existing Codex install, generates a
small refactor fixture plus a large NOTES.md file, runs Codex with throughline's
compact prompt, then reports whether the run compacted and whether the refactor
completed.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / "skills" / "throughline" / "assets" / "compact_prompt.md"


def write_fixture(work: Path, notes_lines: int) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "calc.py").write_text(
        """import sys

def add(a, b):
    return a + b

def sub(a, b):
    return a - b

def mul(a, b):
    return a * b

def div(a, b):
    return a / b

if __name__ == "__main__":
    op, a, b = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    fns = {"add": add, "sub": sub, "mul": mul, "div": div}
    print(fns[op](a, b))
""",
        encoding="utf-8",
    )
    lines = [
        f"- convention {i:04d}: keep functions pure; module owners rotate quarterly; "
        f"ticket REF-{i:04d} tracks legacy cleanup item {i} in the historical ledger."
        for i in range(notes_lines)
    ]
    (work / "NOTES.md").write_text(
        "# Project Conventions Ledger\n\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    (work / ".throughline.md").write_text(
        """# THROUGHLINE
meta:
  task_id: calc-to-class
  size_budget_bytes: 8000

## === OBJECTIVE LOCK (verbatim) ===
OBJECTIVE: Refactor calc.py so the four arithmetic functions become methods of a Calculator class, keeping the CLI behavior identical.
TASK TYPE: refactor

## === OUT OF SCOPE ===
- Adding new operations
- Changing CLI argument format

## === PROGRESS CHECKLIST ===
- [ ] Read project conventions
- [ ] Introduce Calculator class
- [ ] Move add/sub/mul/div into methods
- [ ] Point CLI at the class
- [ ] Verify CLI output unchanged

## === NEXT ACTION ===
Read NOTES.md once, then advance to Calculator refactor.

## === COMPLETED INPUTS / DO-NOT-REPEAT ===
- none yet
""",
        encoding="utf-8",
    )


def _top_level_value(lines, key):
    prefix = f"{key} ="
    for line in lines:
        if line.strip().startswith(prefix):
            return line.strip()
    return None


def _section(lines, header):
    out = []
    active = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if active:
                break
            active = stripped == header
        if active:
            out.append(line)
    return out


def copy_codex_home(src: Path, dst: Path, strip_service_tier: bool, minimal_config: bool) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    auth = src / "auth.json"
    config = src / "config.toml"
    if auth.exists():
        shutil.copy2(auth, dst / "auth.json")
    if not config.exists():
        raise SystemExit(f"missing config: {config}")
    text = config.read_text(encoding="utf-8")
    if strip_service_tier:
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("service_tier")
        ) + "\n"
    if minimal_config:
        lines = text.splitlines()
        provider_line = _top_level_value(lines, "model_provider")
        if not provider_line:
            raise SystemExit("config.toml must define top-level model_provider for minimal mode")
        provider_name = provider_line.split("=", 1)[1].strip().strip('"')
        provider_section = _section(lines, f"[model_providers.{provider_name}]")
        if not provider_section:
            raise SystemExit(f"missing provider section [model_providers.{provider_name}]")
        kept = [
            _top_level_value(lines, "model") or 'model = "gpt-5.1-codex-max"',
            provider_line,
            _top_level_value(lines, "disable_response_storage") or "disable_response_storage = true",
            _top_level_value(lines, "model_context_window") or "model_context_window = 400000",
            "",
            *provider_section,
        ]
        text = "\n".join(kept).rstrip() + "\n"
    (dst / "config.toml").write_text(text, encoding="utf-8")


def latest_rollout(home: Path):
    files = sorted(home.glob("sessions/**/rollout-*.jsonl"))
    return files[-1] if files else None


def parse_rollout(path: Path):
    compactions = []
    if not path or not path.exists():
        return compactions
    for line in path.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("type") == "compacted":
            compactions.append(item)
    return compactions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codex-home", default=os.path.expanduser("~/.codex"))
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--token-limit", type=int, default=40000)
    ap.add_argument("--notes-lines", type=int, default=2200)
    ap.add_argument("--work-root", default=None, help="default: temporary directory")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--strip-service-tier", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--minimal-config", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--reasoning-effort", default="low")
    args = ap.parse_args()

    base = Path(args.work_root) if args.work_root else Path(tempfile.mkdtemp(prefix="throughline-trial-"))
    home = base / ".codex"
    work = base / "work"
    copy_codex_home(Path(args.codex_home), home, args.strip_service_tier, args.minimal_config)
    write_fixture(work, args.notes_lines)

    prompt = (
        "Your task: refactor calc.py so that add, sub, mul, and div become methods of "
        "a new class called Calculator, while keeping the command-line behavior identical.\n\n"
        "Use throughline: .throughline.md is the task state. Respect COMPLETED INPUTS / "
        "DO-NOT-REPEAT. If a compaction summary says NOTES.md was already read, advance "
        "to editing calc.py.\n\n"
        "First, read the ENTIRE contents of NOTES.md exactly once with `cat NOTES.md`. "
        "Then implement the refactor in calc.py. When done, run `python3 calc.py add 2 3` "
        "and update .throughline.md."
    )
    out = base / "run.jsonl"
    err = base / "run.err"
    cmd = [
        "codex",
        "exec",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "-C",
        str(work),
        "-c",
        f'model_auto_compact_token_limit={args.token_limit}',
        "-c",
        f'experimental_compact_prompt_file="{PROMPT}"',
        "-c",
        f'model_reasoning_effort="{args.reasoning_effort}"',
        prompt,
    ]
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)

    with out.open("w", encoding="utf-8") as stdout, err.open("w", encoding="utf-8") as stderr:
        proc = subprocess.Popen(cmd, cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
        start = time.time()
        while proc.poll() is None and time.time() - start < args.timeout:
            if "class Calculator" in (work / "calc.py").read_text(encoding="utf-8"):
                break
            time.sleep(5)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    rollout = latest_rollout(home)
    compactions = parse_rollout(rollout)
    final_calc = (work / "calc.py").read_text(encoding="utf-8")
    final_card = (work / ".throughline.md").read_text(encoding="utf-8")
    last_summary = compactions[-1]["payload"]["message"] if compactions else ""
    result = {
        "root": str(base),
        "rollout": str(rollout) if rollout else None,
        "compactions": len(compactions),
        "has_objective_lock": "OBJECTIVE LOCK" in last_summary,
        "has_completed_inputs": "COMPLETED INPUTS / DO-NOT-REPEAT" in last_summary,
        "calculator_class": "class Calculator" in final_calc,
        "card_checked_items": final_card.count("[x]"),
        "jsonl": str(out),
        "stderr": str(err),
    }
    print(json.dumps(result, indent=2))
    if not args.keep and not result["calculator_class"]:
        print("kept failed trial artifacts for inspection", file=sys.stderr)


if __name__ == "__main__":
    main()
