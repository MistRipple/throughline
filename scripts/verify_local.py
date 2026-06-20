#!/usr/bin/env python3
"""Local verification for the throughline project.

This test suite avoids live model calls. It verifies the deterministic parts that
must hold before running an expensive Codex/Claude compaction trial.
"""
import json
import os
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "throughline"
HOOK = SKILL / "scripts" / "throughline_hook.py"
INSTALL = SKILL / "scripts" / "install.py"


def ok(name):
    print(f"ok - {name}")


def fail(name, detail):
    print(f"not ok - {name}: {detail}", file=sys.stderr)
    raise SystemExit(1)


def assert_contains(path, needles, name):
    text = path.read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        fail(name, f"missing {missing} in {path}")
    ok(name)


def run(cmd, *, env=None, cwd=None, input_text=None):
    return subprocess.run(
        cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        check=False,
    )


def test_prompt_contract():
    assert_contains(
        SKILL / "assets" / "compact_prompt.md",
        [
            "=== OBJECTIVE LOCK (verbatim) ===",
            "=== PROGRESS CHECKLIST ===",
            "=== COMPLETED INPUTS / DO-NOT-REPEAT ===",
            "=== NEXT ACTION ===",
            "NEVER reset all items to unchecked",
            "Never make the next model re-read a large file",
            "CARD STALE",
        ],
        "compact prompt carries objective, progress, completed inputs, and anti-loop rules",
    )


def test_card_contract():
    assert_contains(
        SKILL / "assets" / "throughline-card.template.md",
        [
            "size_budget_bytes: 8000",
            "=== OBJECTIVE LOCK (verbatim) ===",
            "=== COMPLETED INPUTS / DO-NOT-REPEAT ===",
        ],
        "card template has bounded objective and completed-input sections",
    )
    assert_contains(
        ROOT / "examples" / "refactor.throughline.md",
        ["COMPLETED INPUTS / DO-NOT-REPEAT", "cat NOTES.md"],
        "example demonstrates completed-input anti-loop usage",
    )


def test_hook_resolution():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        nested = root / "a" / "b"
        nested.mkdir(parents=True)
        card = root / ".throughline.md"
        card.write_text("# THROUGHLINE\nOBJECTIVE: keep original\n", encoding="utf-8")

        payload = json.dumps({"cwd": str(nested), "hookEventName": "UserPromptSubmit"})
        proc = run([sys.executable, str(HOOK)], input_text=payload)
        if proc.returncode != 0:
            fail("hook resolves card by walking up", proc.stderr)
        data = json.loads(proc.stdout)
        context = data["hookSpecificOutput"]["additionalContext"]
        if str(card) not in context or "OBJECTIVE: keep original" not in context:
            fail("hook resolves card by walking up", proc.stdout)
        ok("hook resolves card by walking up")

        explicit = root / "explicit.md"
        explicit.write_text("# THROUGHLINE\nOBJECTIVE: explicit\n", encoding="utf-8")
        env = os.environ.copy()
        env["THROUGHLINE_CARD"] = str(explicit)
        proc = run([sys.executable, str(HOOK)], env=env, input_text=payload)
        data = json.loads(proc.stdout)
        if "OBJECTIVE: explicit" not in data["hookSpecificOutput"]["additionalContext"]:
            fail("hook honors THROUGHLINE_CARD override", proc.stdout)
        ok("hook honors THROUGHLINE_CARD override")


def test_hook_no_card_is_silent():
    with tempfile.TemporaryDirectory() as td:
        payload = json.dumps({"cwd": td, "hookEventName": "UserPromptSubmit"})
        proc = run([sys.executable, str(HOOK)], input_text=payload)
        if proc.returncode != 0 or proc.stdout.strip():
            fail("hook is silent without a card", proc.stdout + proc.stderr)
        ok("hook is silent without a card")


def test_precompact_snapshots_card():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        card.write_text(
            "# THROUGHLINE\nOBJECTIVE: keep original\n"
            "COMPLETED INPUTS / DO-NOT-REPEAT: cat NOTES.md done\n",
            encoding="utf-8",
        )
        payload = json.dumps({"cwd": str(root), "hook_event_name": "PreCompact"})
        proc = run([sys.executable, str(HOOK)], input_text=payload)
        if proc.returncode != 0:
            fail("PreCompact hook runs", proc.stderr)
        if proc.stdout.strip():
            fail("PreCompact emits no additionalContext", proc.stdout)
        backup = root / ".throughline.precompact.bak"
        if not backup.is_file():
            fail("PreCompact writes a snapshot", "no backup file")
        if backup.read_text(encoding="utf-8") != card.read_text(encoding="utf-8"):
            fail("PreCompact snapshot matches the card", "content mismatch")
        ok("PreCompact snapshots the card without emitting context")


def test_degraded_card_recovers_from_snapshot():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        card.write_text(
            "# THROUGHLINE\nOBJECTIVE: refactor X into Y\n"
            "COMPLETED INPUTS / DO-NOT-REPEAT: cat NOTES.md done\n",
            encoding="utf-8",
        )
        # snapshot, then degrade the live card (objective lost)
        snap_payload = json.dumps({"cwd": str(root), "hook_event_name": "PreCompact"})
        run([sys.executable, str(HOOK)], input_text=snap_payload)
        card.write_text("summary: tighten existing code\n", encoding="utf-8")

        payload = json.dumps(
            {"cwd": str(root), "hook_event_name": "SessionStart", "matcher": "compact"}
        )
        proc = run([sys.executable, str(HOOK)], input_text=payload)
        if proc.returncode != 0:
            fail("recovery hook runs", proc.stderr)
        data = json.loads(proc.stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        if "RESTORED from the pre-compaction snapshot" not in ctx:
            fail("degraded card is flagged as restored", ctx[:200])
        if "refactor X into Y" not in ctx:
            fail("objective recovered into injected context", ctx[:200])
        if "refactor X into Y" not in card.read_text(encoding="utf-8"):
            fail("live card rewritten from snapshot", card.read_text(encoding="utf-8"))
        ok("degraded card recovers from pre-compaction snapshot")


def test_healthy_card_not_overwritten_by_snapshot():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        card.write_text("# THROUGHLINE\nOBJECTIVE: live and healthy\n", encoding="utf-8")
        (root / ".throughline.precompact.bak").write_text(
            "# THROUGHLINE\nOBJECTIVE: stale snapshot\n", encoding="utf-8"
        )
        payload = json.dumps({"cwd": str(root), "hook_event_name": "UserPromptSubmit"})
        proc = run([sys.executable, str(HOOK)], input_text=payload)
        data = json.loads(proc.stdout)
        ctx = data["hookSpecificOutput"]["additionalContext"]
        if "RESTORED" in ctx or "stale snapshot" in ctx:
            fail("healthy card is never replaced by snapshot", ctx[:200])
        if "live and healthy" not in ctx:
            fail("healthy card is injected as-is", ctx[:200])
        ok("healthy live card is never overwritten by the snapshot")


def test_narrowed_card_triggers_restore():
    """The exact drift case: a card narrowed to 'harden existing code' must be treated
    as degraded and restored from the snapshot, not accepted as healthy."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        card.write_text(
            "# THROUGHLINE\nOBJECTIVE: Refactor calc.py into a Calculator class\n", encoding="utf-8"
        )
        run([sys.executable, str(HOOK)],
            input_text=json.dumps({"cwd": str(root), "hook_event_name": "PreCompact"}))
        # objective collapses to the narrowed form
        card.write_text("OBJECTIVE: harden the existing code\n", encoding="utf-8")
        proc = run([sys.executable, str(HOOK)],
                   input_text=json.dumps({"cwd": str(root), "hook_event_name": "UserPromptSubmit"}))
        ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        if "Refactor calc.py into a Calculator class" not in ctx:
            fail("narrowed card is restored to original objective", ctx[:200])
        if "RESTORED" not in ctx:
            fail("narrowed card restore is flagged", ctx[:200])
        ok("narrowed objective triggers restore from snapshot")


def test_placeholder_card_triggers_restore():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        card.write_text("# THROUGHLINE\nOBJECTIVE: real built feature\n", encoding="utf-8")
        run([sys.executable, str(HOOK)],
            input_text=json.dumps({"cwd": str(root), "hook_event_name": "PreCompact"}))
        # card reset to unfilled template placeholder
        card.write_text("OBJECTIVE: <verbatim original objective>\n", encoding="utf-8")
        proc = run([sys.executable, str(HOOK)],
                   input_text=json.dumps({"cwd": str(root), "hook_event_name": "UserPromptSubmit"}))
        ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        if "real built feature" not in ctx:
            fail("placeholder card is restored from snapshot", ctx[:200])
        ok("placeholder objective triggers restore from snapshot")


def test_degraded_card_cannot_poison_snapshot():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        snap = root / ".throughline.precompact.bak"
        card.write_text("# THROUGHLINE\nOBJECTIVE: build feature Z end to end\n", encoding="utf-8")
        run([sys.executable, str(HOOK)],
            input_text=json.dumps({"cwd": str(root), "hook_event_name": "PreCompact"}))
        card.write_text("OBJECTIVE: harden the existing code\n", encoding="utf-8")
        # second PreCompact with a degraded card must NOT overwrite the good snapshot
        run([sys.executable, str(HOOK)],
            input_text=json.dumps({"cwd": str(root), "hook_event_name": "PreCompact"}))
        if "build feature Z end to end" not in snap.read_text(encoding="utf-8"):
            fail("degraded card poisoned the snapshot", snap.read_text(encoding="utf-8"))
        ok("degraded card cannot overwrite a healthy snapshot")


def test_narrow_detection_matrix():
    """Narrowing detection must catch real drift without false-positiving on
    legitimate builds that merely mention a word like 'validate' or 'existing'."""
    spec = importlib.util.spec_from_file_location("tl_hook", str(HOOK))
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    healthy_ok = [
        "Refactor to validate inputs against the new schema",
        "Build a validation service for the existing API",
        "Refactor calc.py into a Calculator class",
        "Migrate the existing auth module to OAuth2",
        "Build a hardening dashboard feature for users",
    ]
    degraded = [
        "harden the existing code",
        "Harden the existing parser",
        "Clean up the current module",
        "tighten existing behavior and validate current code",
        "just stabilize the existing implementation",
        "clean up the code",
    ]
    for obj in healthy_ok:
        if not h._healthy("OBJECTIVE: " + obj):
            fail("legitimate build stays healthy", obj)
    for obj in degraded:
        if h._healthy("OBJECTIVE: " + obj):
            fail("narrowed objective is detected as degraded", obj)
    ok("narrow detection catches drift without false-positiving on real builds")


def test_claude_install_includes_precompact():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        env = os.environ.copy()
        env["HOME"] = str(home)
        proc = run([sys.executable, str(INSTALL), "--claude"], env=env)
        if proc.returncode != 0:
            fail("claude install runs", proc.stderr)
        settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        events = settings["hooks"]
        for needed in ("PreCompact", "SessionStart", "UserPromptSubmit"):
            if needed not in events:
                fail("claude install wires PreCompact + compact recovery", f"missing {needed}")
        sess_matchers = {e.get("matcher") for e in events["SessionStart"]}
        if "compact" not in sess_matchers:
            fail("claude SessionStart includes compact matcher", str(sess_matchers))
        ok("claude install wires PreCompact snapshot and post-compact re-injection")


def test_claude_installer_idempotent_and_preserves_foreign_hooks():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps({"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "echo foreign"}]}]}}),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)

        for _ in range(3):
            proc = run([sys.executable, str(INSTALL), "--claude"], env=env)
            if proc.returncode != 0:
                fail("claude installer runs", proc.stderr)
        data = json.loads(settings.read_text(encoding="utf-8"))
        if len(data["hooks"]["SessionStart"]) != 3:  # startup/resume/compact
            fail("claude install idempotent for SessionStart", json.dumps(data, indent=2))
        if len(data["hooks"]["UserPromptSubmit"]) != 1:
            fail("claude install idempotent for UserPromptSubmit", json.dumps(data, indent=2))
        if "Stop" not in data["hooks"]:
            fail("claude install preserves foreign hooks", json.dumps(data, indent=2))
        ok("claude installer is idempotent and preserves foreign hooks")

        proc = run([sys.executable, str(INSTALL), "--uninstall", "--claude"], env=env)
        if proc.returncode != 0:
            fail("claude uninstaller runs", proc.stderr)
        data = json.loads(settings.read_text(encoding="utf-8"))
        if "SessionStart" in data["hooks"] or "PreCompact" in data["hooks"]:
            fail("claude uninstaller removes throughline hooks", json.dumps(data, indent=2))
        if "Stop" not in data["hooks"]:
            fail("claude uninstaller preserves foreign hooks", json.dumps(data, indent=2))
        ok("claude uninstaller removes throughline hooks and preserves foreign hooks")


def test_codex_install_cleans_legacy_hooks_json():
    """Older installs left a hooks.json + a rejected string key. The new Codex
    install must remove our entries from a stray hooks.json (preserving foreign)."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        codex_home = home / ".codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
        legacy = codex_home / "hooks.json"
        legacy.write_text(json.dumps({"hooks": {
            "Stop": [{"hooks": [{"type": "command", "command": "echo foreign"}]}],
            "SessionStart": [{"matcher": "startup", "hooks": [
                {"type": "command", "command": 'python3 "x/throughline_hook.py"'}]}],
        }}), encoding="utf-8")
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)
        proc = run([sys.executable, str(INSTALL), "--codex"], env=env)
        if proc.returncode != 0:
            fail("codex install runs with legacy hooks.json", proc.stderr)
        data = json.loads(legacy.read_text(encoding="utf-8"))
        if "SessionStart" in data.get("hooks", {}):
            fail("legacy throughline entries removed from hooks.json", json.dumps(data))
        if "Stop" not in data.get("hooks", {}):
            fail("foreign entries preserved in legacy hooks.json", json.dumps(data))
        ok("codex install cleans legacy throughline hooks.json and keeps foreign hooks")


def _parse_toml(text):
    try:
        import tomllib  # py3.11+
        return tomllib.loads(text)
    except ModuleNotFoundError:
        try:
            import tomli
            return tomli.loads(text)
        except ModuleNotFoundError:
            return None  # no parser available; skip structural assert


def test_codex_inline_hooks_wiring():
    """Codex rejects `hooks = "path"`; hooks must be inline [hooks.*] tables.
    Verify the installer writes a valid, idempotent, parseable inline block and
    that uninstall removes it cleanly while preserving the user's config."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        codex_home = home / ".codex"
        codex_home.mkdir()
        cfg = codex_home / "config.toml"
        cfg.write_text(
            'model = "gpt-5"\n\n[history]\npersistence = "save-all"\n', encoding="utf-8"
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)

        for _ in range(3):
            proc = run([sys.executable, str(INSTALL), "--codex"], env=env)
            if proc.returncode != 0:
                fail("inline hooks install runs", proc.stderr)
        text = cfg.read_text(encoding="utf-8")

        # exactly one managed block, never the rejected string form
        if text.count("# >>> throughline") != 1:
            fail("exactly one managed block after repeated installs", text)
        if 'hooks = "./hooks.json"' in text or 'hooks="./hooks.json"' in text:
            fail("must not write the rejected string hooks key", text)
        for needed in ("[[hooks.UserPromptSubmit]]", "[[hooks.SessionStart]]",
                       'matcher = "startup"', 'matcher = "resume"',
                       "experimental_compact_prompt_file"):
            if needed not in text:
                fail("inline hooks block has the required tables", f"missing {needed}")
        if not (codex_home / "config.toml.throughline.bak").is_file():
            fail("backup written before edit", text)

        parsed = _parse_toml(text)
        if parsed is not None:
            hooks = parsed.get("hooks", {})
            ups = hooks.get("UserPromptSubmit", [])
            ss = hooks.get("SessionStart", [])
            if not ups or not ups[0]["hooks"][0]["command"].endswith('throughline_hook.py"'):
                fail("parsed UserPromptSubmit hook points at our injector", str(ups))
            matchers = sorted(g.get("matcher") for g in ss)
            if matchers != ["resume", "startup"]:
                fail("parsed SessionStart has startup+resume matchers", str(matchers))
            if "model" not in parsed or "history" not in parsed:
                fail("user config preserved through inline-hooks install", str(parsed.keys()))
        ok("codex inline hooks block is valid, idempotent, and parseable")

        proc = run([sys.executable, str(INSTALL), "--uninstall", "--codex"], env=env)
        if proc.returncode != 0:
            fail("inline hooks uninstall runs", proc.stderr)
        text = cfg.read_text(encoding="utf-8")
        if "throughline" in text or "[hooks" in text or "experimental_compact_prompt_file" in text:
            fail("uninstall removes the entire managed block", text)
        if 'model = "gpt-5"' not in text or "[history]" not in text:
            fail("uninstall preserves user config", text)
        parsed = _parse_toml(text)
        if parsed is not None and ("model" not in parsed or "history" not in parsed):
            fail("config still parses after uninstall", str(parsed))
        ok("codex uninstall removes the block and leaves a valid config")


def main():
    test_prompt_contract()
    test_card_contract()
    test_hook_resolution()
    test_hook_no_card_is_silent()
    test_precompact_snapshots_card()
    test_degraded_card_recovers_from_snapshot()
    test_healthy_card_not_overwritten_by_snapshot()
    test_narrowed_card_triggers_restore()
    test_placeholder_card_triggers_restore()
    test_degraded_card_cannot_poison_snapshot()
    test_narrow_detection_matrix()
    test_claude_install_includes_precompact()
    test_claude_installer_idempotent_and_preserves_foreign_hooks()
    test_codex_install_cleans_legacy_hooks_json()
    test_codex_inline_hooks_wiring()


if __name__ == "__main__":
    main()
