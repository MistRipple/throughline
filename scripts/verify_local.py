#!/usr/bin/env python3
"""Local verification for the throughline project.

This test suite avoids live model calls. It verifies the deterministic parts that
must hold before running an expensive Codex compaction trial.
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
CARD = SKILL / "scripts" / "card.py"


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


def test_injection_is_token_bounded():
    """An oversized card must never blow up context: injection is hard-capped."""
    spec = importlib.util.spec_from_file_location("tl_hook_cap", str(HOOK))
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # 50KB card (far past the 8KB template budget)
        (root / ".throughline.md").write_text(
            "# THROUGHLINE\nOBJECTIVE: build the thing\n" + ("X" * 50000), encoding="utf-8"
        )
        proc = run([sys.executable, str(HOOK)],
                   input_text=json.dumps({"cwd": str(root), "hook_event_name": "UserPromptSubmit"}))
        ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        if "truncated to injection cap" not in ctx:
            fail("oversized card is truncated", f"len={len(ctx)}")
        # prefix + capped body must stay within a small, fixed bound (~2.4k tokens)
        if len(ctx) > h.INJECT_CAP + 600:
            fail("injection stays within the hard cap", f"len={len(ctx)} cap={h.INJECT_CAP}")
        ok("card injection is token-bounded regardless of card size")


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
        proc = run([sys.executable, str(INSTALL)], env=env)
        if proc.returncode != 0:
            fail("codex install runs with legacy hooks.json", proc.stderr)
        data = json.loads(legacy.read_text(encoding="utf-8"))
        if "SessionStart" in data.get("hooks", {}):
            fail("legacy throughline entries removed from hooks.json", json.dumps(data))
        if "Stop" not in data.get("hooks", {}):
            fail("foreign entries preserved in legacy hooks.json", json.dumps(data))
        ok("codex install cleans legacy throughline hooks.json and keeps foreign hooks")


def test_installer_has_single_codex_entrypoint():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        codex_home = home / ".codex"
        codex_home.mkdir()
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)

        proc = run([sys.executable, str(INSTALL), "--print"], env=env)
        if proc.returncode != 0:
            fail("installer --print succeeds", proc.stderr)
        data = json.loads(proc.stdout)
        if sorted(data.keys()) != ["codex"]:
            fail("installer --print exposes only the Codex path", proc.stdout)
        ok("installer --print exposes only the Codex path")

        for flag in ("--codex", "--claude"):
            proc = run([sys.executable, str(INSTALL), flag], env=env)
            if proc.returncode == 0:
                fail(f"installer rejects removed flag {flag}", proc.stdout)
        ok("installer rejects removed Codex/Claude compatibility flags")


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
            proc = run([sys.executable, str(INSTALL)], env=env)
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

        proc = run([sys.executable, str(INSTALL), "--uninstall"], env=env)
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


def test_card_init_archives_previous_and_resets():
    """A new task gets a new card; the previous card must be archived (its only backup,
    since the disk card is gitignored), and the new card carries the new objective."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        proc = run([sys.executable, str(CARD), "init",
                    "--objective", "Build a NEW email notification feature",
                    "--task-type", "feature"], cwd=str(root))
        if proc.returncode != 0:
            fail("card init creates a first card", proc.stderr)
        first = card.read_text(encoding="utf-8")
        if "OBJECTIVE: Build a NEW email notification feature" not in first:
            fail("first card carries the verbatim objective", first[:200])
        if "status: active" not in first:
            fail("new card is marked active", first[:200])

        proc = run([sys.executable, str(CARD), "init",
                    "--objective", "Add OAuth2 login", "--task-type", "feature"], cwd=str(root))
        if proc.returncode != 0:
            fail("card init creates a second card", proc.stderr)
        second = card.read_text(encoding="utf-8")
        if "OBJECTIVE: Add OAuth2 login" not in second:
            fail("second card carries the new objective", second[:200])
        if "email notification" in second:
            fail("new card does not inherit the previous objective", second[:200])

        archive = root / ".throughline" / "archive"
        backups = list(archive.glob("*.md"))
        if len(backups) != 1:
            fail("previous card is archived exactly once", str(backups))
        if "Build a NEW email notification feature" not in backups[0].read_text(encoding="utf-8"):
            fail("archived card preserves the previous objective", backups[0].name)

        # Objective text is written verbatim: regex-y values must not be read as backreferences.
        tricky = r"Fix \\g<bug> and \\1 in C:\\path"
        proc = run([sys.executable, str(CARD), "init",
                    "--objective", tricky, "--task-type", "bugfix"], cwd=str(root))
        if proc.returncode != 0:
            fail("card init handles regex metacharacters in the objective", proc.stderr)
        if tricky not in card.read_text(encoding="utf-8"):
            fail("objective with backreference-like text is stored verbatim", card.read_text(encoding="utf-8")[:200])
        ok("card init archives the previous card and resets the objective")


def test_hook_silent_on_done_and_placeholder_cards():
    """The injector must not feed a stale card into the next task: a done card or an
    unfilled template placeholder both yield no additionalContext."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        payload = json.dumps({"cwd": str(root), "hookEventName": "UserPromptSubmit"})

        card.write_text("# THROUGHLINE\nmeta:\n  status: done\nOBJECTIVE: shipped feature\n",
                        encoding="utf-8")
        proc = run([sys.executable, str(HOOK)], input_text=payload)
        if proc.returncode != 0 or proc.stdout.strip():
            fail("hook is silent for a done card", proc.stdout + proc.stderr)

        card.write_text("# THROUGHLINE\nOBJECTIVE: <verbatim original objective>\n",
                        encoding="utf-8")
        proc = run([sys.executable, str(HOOK)], input_text=payload)
        if proc.returncode != 0 or proc.stdout.strip():
            fail("hook is silent for an unfilled placeholder card", proc.stdout + proc.stderr)

        card.write_text("# THROUGHLINE\nmeta:\n  status: active\nOBJECTIVE: real live goal\n",
                        encoding="utf-8")
        proc = run([sys.executable, str(HOOK)], input_text=payload)
        ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        if "real live goal" not in ctx:
            fail("hook still injects an active, filled card", proc.stdout)
        ok("hook stays silent for done/placeholder cards and injects active ones")


def main():
    test_prompt_contract()
    test_card_contract()
    test_hook_resolution()
    test_hook_no_card_is_silent()
    test_injection_is_token_bounded()
    test_codex_install_cleans_legacy_hooks_json()
    test_installer_has_single_codex_entrypoint()
    test_codex_inline_hooks_wiring()
    test_card_init_archives_previous_and_resets()
    test_hook_silent_on_done_and_placeholder_cards()


if __name__ == "__main__":
    main()
