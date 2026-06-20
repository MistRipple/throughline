#!/usr/bin/env python3
"""Local verification for the throughline project.

This test suite avoids live model calls. It verifies the deterministic parts that
must hold before running an expensive Codex/Claude compaction trial.
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


def test_installer_idempotent_and_preserves_foreign_hooks():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        codex_home = home / ".codex"
        codex_home.mkdir()
        hooks = codex_home / "hooks.json"
        hooks.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command", "command": "echo foreign"}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)

        for _ in range(3):
            proc = run([sys.executable, str(INSTALL), "--codex"], env=env)
            if proc.returncode != 0:
                fail("installer runs", proc.stderr)
        data = json.loads(hooks.read_text(encoding="utf-8"))
        if len(data["hooks"]["SessionStart"]) != 2:
            fail("installer is idempotent for SessionStart", json.dumps(data, indent=2))
        if len(data["hooks"]["UserPromptSubmit"]) != 1:
            fail("installer is idempotent for UserPromptSubmit", json.dumps(data, indent=2))
        if "Stop" not in data["hooks"]:
            fail("installer preserves foreign hooks", json.dumps(data, indent=2))
        ok("installer is idempotent and preserves foreign hooks")

        proc = run([sys.executable, str(INSTALL), "--uninstall", "--codex"], env=env)
        if proc.returncode != 0:
            fail("uninstaller runs", proc.stderr)
        data = json.loads(hooks.read_text(encoding="utf-8"))
        if "SessionStart" in data["hooks"] or "UserPromptSubmit" in data["hooks"]:
            fail("uninstaller removes throughline hooks", json.dumps(data, indent=2))
        if "Stop" not in data["hooks"]:
            fail("uninstaller preserves foreign hooks", json.dumps(data, indent=2))
        ok("uninstaller removes throughline hooks and preserves foreign hooks")


def test_config_toml_wiring_is_safe():
    with tempfile.TemporaryDirectory() as td:
        home = Path(td)
        codex_home = home / ".codex"
        codex_home.mkdir()
        cfg = codex_home / "config.toml"
        cfg.write_text(
            'model = "gpt-5"\nhooks = "./my-hooks.json"\n\n[history]\npersistence = "save-all"\n',
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["HOME"] = str(home)
        env["CODEX_HOME"] = str(codex_home)

        for _ in range(3):
            proc = run([sys.executable, str(INSTALL), "--codex"], env=env)
            if proc.returncode != 0:
                fail("config wiring runs", proc.stderr)
        text = cfg.read_text(encoding="utf-8")
        compact_lines = [l for l in text.splitlines() if "experimental_compact_prompt_file" in l]
        if len(compact_lines) != 1:
            fail("compact prompt key written exactly once", text)
        # user's own top-level hooks key must be preserved, not duplicated
        if 'hooks = "./my-hooks.json"' not in text:
            fail("user hooks key preserved", text)
        if text.count("hooks =") != 1:
            fail("user hooks key not duplicated", text)
        # top-level key must sit before the first table header to stay top-level
        if text.index("experimental_compact_prompt_file") > text.index("[history]"):
            fail("compact key stays above the first table", text)
        if not (codex_home / "config.toml.throughline.bak").is_file():
            fail("backup written before edit", text)
        ok("config wiring inserts compact key safely and preserves user keys")

        proc = run([sys.executable, str(INSTALL), "--uninstall", "--codex"], env=env)
        if proc.returncode != 0:
            fail("config wiring uninstall runs", proc.stderr)
        text = cfg.read_text(encoding="utf-8")
        if "throughline-managed" in text or "experimental_compact_prompt_file" in text:
            fail("uninstall removes managed config lines", text)
        if 'hooks = "./my-hooks.json"' not in text or "[history]" not in text:
            fail("uninstall preserves user config", text)
        ok("config wiring uninstall removes only managed lines")


def main():
    test_prompt_contract()
    test_card_contract()
    test_hook_resolution()
    test_hook_no_card_is_silent()
    test_installer_idempotent_and_preserves_foreign_hooks()
    test_config_toml_wiring_is_safe()


if __name__ == "__main__":
    main()
