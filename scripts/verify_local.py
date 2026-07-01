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


def test_card_new_archives_previous_and_resets():
    """`new` opens a fresh objective line and unconditionally archives the previous
    card (its only backup, since the disk card is gitignored). The new card carries
    the new objective and never inherits the old one. `init` is a plain alias."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        proc = run([sys.executable, str(CARD), "new",
                    "--objective", "Build a NEW email notification feature",
                    "--task-type", "feature"], cwd=str(root))
        if proc.returncode != 0:
            fail("card new creates a first card", proc.stderr)
        first = card.read_text(encoding="utf-8")
        if "OBJECTIVE: Build a NEW email notification feature" not in first:
            fail("first card carries the verbatim objective", first[:200])
        if "status: active" not in first:
            fail("new card is marked active", first[:200])

        # `new` over an ACTIVE card just archives it - no flag, no prompt, no refusal.
        proc = run([sys.executable, str(CARD), "new",
                    "--objective", "Add OAuth2 login", "--task-type", "feature"], cwd=str(root))
        if proc.returncode != 0:
            fail("card new replaces an active card without a flag", proc.stderr)
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

        # `init` alias behaves identically to `new`.
        proc = run([sys.executable, str(CARD), "init",
                    "--objective", "Via the init alias", "--task-type", "feature"], cwd=str(root))
        if proc.returncode != 0 or "OBJECTIVE: Via the init alias" not in card.read_text(encoding="utf-8"):
            fail("init alias maps to new", proc.stdout + proc.stderr)

        # Objective text is written verbatim: regex-y values must not be read as backreferences.
        tricky = r"Fix \\g<bug> and \\1 in C:\\path"
        proc = run([sys.executable, str(CARD), "new",
                    "--objective", tricky, "--task-type", "bugfix"], cwd=str(root))
        if proc.returncode != 0:
            fail("card new handles regex metacharacters in the objective", proc.stderr)
        if tricky not in card.read_text(encoding="utf-8"):
            fail("objective with backreference-like text is stored verbatim", card.read_text(encoding="utf-8")[:200])
        ok("card new archives the previous card and resets the objective")


def test_card_done_resume_and_template_guard():
    """done and resume are inverses on a real objective, resume never archives, and a
    drifted template makes `new` fail (exit 2) without destroying the existing card
    (its only backup). `reopen` is a plain alias for `resume`."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"
        run([sys.executable, str(CARD), "new",
             "--objective", "Ship the dashboard", "--task-type", "feature"], cwd=str(root))

        proc = run([sys.executable, str(CARD), "done"], cwd=str(root))
        if proc.returncode != 0 or "status: done" not in card.read_text(encoding="utf-8"):
            fail("card done sets status: done", proc.stdout + proc.stderr)

        # resume reactivates a done card and never archives it.
        before_archive = list((root / ".throughline" / "archive").glob("*.md"))
        proc = run([sys.executable, str(CARD), "resume"], cwd=str(root))
        if proc.returncode != 0 or "status: active" not in card.read_text(encoding="utf-8"):
            fail("card resume reactivates a done card", proc.stdout + proc.stderr)
        if "status: done" in card.read_text(encoding="utf-8"):
            fail("resume leaves no done status behind", card.read_text(encoding="utf-8")[:200])
        if list((root / ".throughline" / "archive").glob("*.md")) != before_archive:
            fail("resume must not archive the current card", "archive changed on resume")

        # resume on an already-active card is a confirming no-op (still exit 0, unchanged).
        snapshot = card.read_text(encoding="utf-8")
        proc = run([sys.executable, str(CARD), "resume"], cwd=str(root))
        if proc.returncode != 0 or card.read_text(encoding="utf-8") != snapshot:
            fail("resume on an active card is a no-op", proc.stdout + proc.stderr)

        # resume refuses a card with no real objective - there is nothing to resume.
        placeholder = root / "placeholder.md"
        placeholder.write_text("OBJECTIVE: <objective>\nstatus: active\n", encoding="utf-8")
        proc = run([sys.executable, str(CARD), "resume", "--card", str(placeholder)], cwd=str(root))
        if proc.returncode != 2:
            fail("resume refuses a placeholder card (nothing to resume)", proc.stdout + proc.stderr)

        # `reopen` alias reactivates a done card just like resume.
        run([sys.executable, str(CARD), "done"], cwd=str(root))
        proc = run([sys.executable, str(CARD), "reopen"], cwd=str(root))
        if proc.returncode != 0 or "status: active" not in card.read_text(encoding="utf-8"):
            fail("reopen alias maps to resume", proc.stdout + proc.stderr)

        # Template drift: `new` must fail (exit 2) and must NOT overwrite the live card.
        before = card.read_text(encoding="utf-8")
        drift = root / "drift_template.md"
        drift.write_text("# broken template with no fields\n", encoding="utf-8")
        # Drive cmd_new directly with a broken TEMPLATE via a tiny shim.
        shim = root / "shim.py"
        shim.write_text(
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('card', %r)\n" % str(CARD) +
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "m.TEMPLATE = %r\n" % str(drift) +
            "class A:\n"
            "    objective='Drifted objective'; task_type='feature'; task_id=None; card=%r\n" % str(card) +
            "sys.exit(m.cmd_new(A()))\n",
            encoding="utf-8")
        proc = run([sys.executable, str(shim)], cwd=str(root))
        if proc.returncode != 2:
            fail("new fails with exit 2 when the template is missing fields", proc.stdout + proc.stderr)
        if card.read_text(encoding="utf-8") != before:
            fail("a failed new must not overwrite the existing card", "card was modified")
        ok("card done/resume are inverses and template drift fails safely")


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



def test_card_check_flags_budget_and_placeholders():
    """`check` warns on unfilled placeholders and over-cap sections, and --strict
    turns those warnings into a non-zero exit so CI can gate on them."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # The shipped template still has an unfilled OBJECTIVE placeholder.
        tmpl = SKILL / "assets" / "throughline-card.template.md"
        proc = run([sys.executable, str(CARD), "check", "--card", str(tmpl)])
        if proc.returncode != 0 or "unfilled" not in proc.stderr:
            fail("check warns (rc 0) on an unfilled template", proc.stdout + proc.stderr)
        proc = run([sys.executable, str(CARD), "check", "--strict", "--card", str(tmpl)])
        if proc.returncode != 1:
            fail("check --strict exits non-zero on a placeholder objective", proc.stdout + proc.stderr)

        # A filled, in-budget card is clean.
        good = root / "good.md"
        good.write_text(
            "# THROUGHLINE\nmeta:\n  size_budget_bytes: 8000\n  status: active\n"
            "OBJECTIVE: ship the real thing\n",
            encoding="utf-8")
        proc = run([sys.executable, str(CARD), "check", "--strict", "--card", str(good)])
        if proc.returncode != 0:
            fail("check passes a filled, in-budget card", proc.stdout + proc.stderr)

        # Too many DECISIONS entries trips the section cap.
        rows = "\n".join(f"- 2026-01-{i:02d} | decision {i} | reason" for i in range(1, 13))
        over = root / "over.md"
        over.write_text(
            "# THROUGHLINE\nmeta:\n  size_budget_bytes: 8000\n  status: active\n"
            "OBJECTIVE: ship it\n## === DECISIONS ===\n" + rows + "\n",
            encoding="utf-8")
        proc = run([sys.executable, str(CARD), "check", "--strict", "--card", str(over)])
        if proc.returncode != 1 or "DECISIONS" not in proc.stderr:
            fail("check flags an over-cap DECISIONS section", proc.stdout + proc.stderr)
        ok("card check flags budget, section caps, and placeholders")


def test_card_default_resolves_to_git_root():
    """init/done run from a subdirectory must resolve the same root card the hook
    walks up to find, so writer and reader never disagree on the card's location."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        run(["git", "init", "-q", str(root)])
        deep = root / "sub" / "deep"
        deep.mkdir(parents=True)

        proc = run([sys.executable, str(CARD), "init",
                    "--objective", "add streaming API", "--task-type", "feature"],
                   cwd=str(deep))
        if proc.returncode != 0:
            fail("init from a subdir succeeds", proc.stdout + proc.stderr)
        if not (root / ".throughline.md").is_file():
            fail("init anchors the card at the git root, not the subdir",
                 str(list(root.rglob(".throughline.md"))))
        if (deep / ".throughline.md").exists():
            fail("init must not leave a stray card in the subdir", "found subdir card")

        # done from the same subdir touches the root card, not a new one.
        proc = run([sys.executable, str(CARD), "done"], cwd=str(deep))
        if proc.returncode != 0 or "status: done" not in (root / ".throughline.md").read_text(encoding="utf-8"):
            fail("done from a subdir updates the root card", proc.stdout + proc.stderr)
        ok("card default path resolves to the git root from any subdir")



def test_installer_pins_real_interpreter():
    """The hook command must embed the installing interpreter's real path, not a
    bare `python3`, so the hook still fires where `python3` is absent from PATH."""
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        codex_home = home / ".codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text('model = "gpt-5"\n', encoding="utf-8")
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)

        if run([sys.executable, str(INSTALL)], env=env).returncode != 0:
            fail("install runs for interpreter-pinning check", "install failed")
        text = (codex_home / "config.toml").read_text(encoding="utf-8")

        # The command names our injector via an absolute interpreter path, and
        # never leaves a bare `python3 "...` that a minimal PATH could not resolve.
        if os.path.basename(sys.executable) not in text:
            fail("hook command embeds the installing interpreter", text)
        if 'command = "python3 ' in text or 'command = "python3"' in text:
            fail("hook command must not use a bare python3", text)
        ok("installer pins the real interpreter path in the hook command")



def test_card_new_and_resume_two_verbs():
    """The two verbs carry intent with no flag or prompt: `new` always opens a fresh
    objective line and archives whatever was there; `resume` always keeps the current
    line and never archives. Coming back to the same task uses `resume`; a genuine
    change of direction uses `new`, and the old objective is recoverable from archive."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        card = root / ".throughline.md"

        if run([sys.executable, str(CARD), "new", "--objective", "Original goal A"],
               cwd=str(root)).returncode != 0:
            fail("new writes the first active card", "nonzero rc")

        # resume is the "same task, keep going" path: objective unchanged, still active.
        proc = run([sys.executable, str(CARD), "resume"], cwd=str(root))
        if proc.returncode != 0:
            fail("resume keeps working the current card", proc.stderr)
        if "Original goal A" not in card.read_text(encoding="utf-8"):
            fail("resume preserves the live objective", card.read_text(encoding="utf-8")[:200])

        # new is the deliberate change of direction: archive A, lock B - no flag needed.
        proc = run([sys.executable, str(CARD), "new", "--objective", "Corrected goal B"],
                   cwd=str(root))
        if proc.returncode != 0:
            fail("new replaces an active card without a flag", proc.stderr)
        now = card.read_text(encoding="utf-8")
        if "Corrected goal B" not in now or "Original goal A" in now:
            fail("new locks the new objective and drops the old", now[:200])
        arch = list((root / ".throughline" / "archive").glob("*.md"))
        if not any("Original goal A" in a.read_text(encoding="utf-8") for a in arch):
            fail("new archives (never deletes) the previous objective for recovery", str(arch))

        # after done, `new` opens the next task exactly the same way.
        if run([sys.executable, str(CARD), "done"], cwd=str(root)).returncode != 0:
            fail("done marks the card complete", "nonzero rc")
        if run([sys.executable, str(CARD), "new", "--objective", "Fresh task C"],
               cwd=str(root)).returncode != 0:
            fail("new opens a task after done", "refused after done")
        if "Fresh task C" not in card.read_text(encoding="utf-8"):
            fail("post-done new locks the new objective", card.read_text(encoding="utf-8")[:200])
        ok("new opens a fresh line and archives; resume keeps the current one")


def main():
    test_prompt_contract()
    test_card_contract()
    test_hook_resolution()
    test_hook_no_card_is_silent()
    test_injection_is_token_bounded()
    test_codex_install_cleans_legacy_hooks_json()
    test_installer_has_single_codex_entrypoint()
    test_codex_inline_hooks_wiring()
    test_card_new_archives_previous_and_resets()
    test_card_done_resume_and_template_guard()
    test_hook_silent_on_done_and_placeholder_cards()
    test_card_check_flags_budget_and_placeholders()
    test_card_default_resolves_to_git_root()
    test_installer_pins_real_interpreter()
    test_card_new_and_resume_two_verbs()


if __name__ == "__main__":
    main()
