#!/usr/bin/env python3
"""End-to-end check of the Claude protection flow without a live model.

Claude has no scriptable knob to force compaction (its compaction is an internal
heuristic, and on a 1M-context model it rarely fires). What we CAN verify
deterministically is that throughline's Claude wiring does the right thing when the
real Claude hook events arrive: PreCompact snapshots the card, and a degraded card is
restored from that snapshot at SessionStart:compact. This drives the installed hook
with real Claude event payload shapes in an isolated HOME.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "throughline"
HOOK = SKILL / "scripts" / "throughline_hook.py"
INSTALL = SKILL / "scripts" / "install.py"


def run(cmd, *, env=None, input_text=None):
    return subprocess.run(cmd, input=input_text, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, check=False)


def main():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        env = os.environ.copy()
        env["HOME"] = str(home)
        proj = home / "proj" / "sub"
        proj.mkdir(parents=True)
        card = home / "proj" / ".throughline.md"
        card.write_text(
            "# THROUGHLINE\nOBJECTIVE: build feature Z end to end\n"
            "COMPLETED INPUTS / DO-NOT-REPEAT: read large spec done\n",
            encoding="utf-8",
        )

        r = run([sys.executable, str(INSTALL), "--claude"], env=env)
        assert r.returncode == 0, r.stderr
        settings = json.loads((home / ".claude" / "settings.json").read_text())
        events = settings["hooks"]
        assert "PreCompact" in events, "PreCompact not wired"
        assert any(e.get("matcher") == "compact" for e in events["SessionStart"]), "compact matcher missing"

        # 1) PreCompact (real Claude payload: trigger auto/manual) snapshots from nested cwd
        pre = json.dumps({"cwd": str(proj), "hook_event_name": "PreCompact", "trigger": "auto"})
        run([sys.executable, str(HOOK)], env=env, input_text=pre)
        snap = home / "proj" / ".throughline.precompact.bak"
        assert snap.is_file(), "PreCompact did not snapshot"

        # 2) compaction degrades the card to a narrowed goal
        card.write_text("compacted: focus on hardening current code\n", encoding="utf-8")

        # 3) SessionStart:compact restores from snapshot and flags it
        post = json.dumps({"cwd": str(proj), "hook_event_name": "SessionStart",
                           "matcher": "compact", "source": "compact"})
        out = run([sys.executable, str(HOOK)], env=env, input_text=post)
        data = json.loads(out.stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        assert "RESTORED from the pre-compaction snapshot" in ctx, "no restore flag"
        assert "build feature Z end to end" in ctx, "objective not recovered in context"
        assert "build feature Z end to end" in card.read_text(), "live card not repaired"

        print("ok - Claude PreCompact snapshot fires from nested cwd")
        print("ok - Claude SessionStart:compact restores degraded card from snapshot")
        print("ok - recovered objective injected and live card repaired")
    print("Claude flow verified (deterministic, no live model).")


if __name__ == "__main__":
    main()
