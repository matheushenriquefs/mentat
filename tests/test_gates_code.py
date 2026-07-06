"""Tests for .agents/lib/gates/code/{precommit,smells}.py — deterministic gates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

_GATES = Path(__file__).resolve().parents[1] / ".agents/lib/gates/code"


# ── precommit gate ───────────────────────────────────────────────────────


def _load_precommit():
    return load_script(_GATES / "precommit.py", "precommit_gate")


def test_precommit_pass_on_empty_chunk(tmp_path):
    pre = _load_precommit()
    assert pre.run(tmp_path) == ("pass", "")


def test_precommit_pass_on_none(tmp_path):
    pre = _load_precommit()
    verdict, msg = pre.run(None)
    assert verdict == "block"
    assert "no chunk path" in msg


def test_precommit_adr_missing_section_blocks(tmp_path):
    pre = _load_precommit()
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-foo.md").write_text("# ADR 0001\n\n## Context\n\n## Decision\n")
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "Consequences" in msg


def test_precommit_adr_complete_passes(tmp_path):
    pre = _load_precommit()
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-foo.md").write_text("# ADR\n\n## Context\nx\n## Decision\ny\n## Consequences\nz\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_agent_missing_frontmatter_blocks(tmp_path):
    pre = _load_precommit()
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "mentat-x.md").write_text("# no frontmatter here\n")
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "frontmatter" in msg


def test_precommit_agent_with_frontmatter_passes(tmp_path):
    pre = _load_precommit()
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "mentat-x.md").write_text("---\nname: x\n---\nbody\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_skill_md_missing_frontmatter_blocks(tmp_path):
    pre = _load_precommit()
    skill_dir = tmp_path / "skills" / "mentat-foo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# no frontmatter here\n")
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "frontmatter" in msg


def test_precommit_skill_md_with_frontmatter_passes(tmp_path):
    pre = _load_precommit()
    skill_dir = tmp_path / "skills" / "mentat-foo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: foo\n---\nbody\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_skills_non_skill_md_passes_without_frontmatter(tmp_path):
    pre = _load_precommit()
    triage = tmp_path / "skills" / "mentat-foo" / "triage"
    triage.mkdir(parents=True)
    (triage / "OUT-OF-SCOPE.md").write_text("# Knowledge doc, no frontmatter\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_workflow_no_links_blocks(tmp_path):
    pre = _load_precommit()
    (tmp_path / "CONTEXT.md").write_text("# title\n\nplain prose, no links\n")
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "cross-ref" in msg


def test_precommit_workflow_with_links_passes(tmp_path):
    pre = _load_precommit()
    (tmp_path / "CONTEXT.md").write_text("# title\n\nSee [details](./docs/x.md)\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_jsonc_suffix_is_not_a_gate_class(tmp_path):
    """A committed .jsonc file is no longer a special gate class — it is ignored."""
    pre = _load_precommit()
    (tmp_path / "cfg.jsonc").write_text("{ this is not json at all ]\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_skips_node_modules(tmp_path):
    pre = _load_precommit()
    (tmp_path / "node_modules" / "x" / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "node_modules" / "x" / "docs" / "adr" / "0001.md").write_text("# missing all sections\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_skips_dot_git(tmp_path):
    pre = _load_precommit()
    (tmp_path / ".git" / "agents").mkdir(parents=True)
    (tmp_path / ".git" / "agents" / "stray.md").write_text("# no frontmatter\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


# ── Slice 3 (G5): missing interpreter blocks, not advises ────────────────────


def test_precommit_missing_bash_blocks(tmp_path, monkeypatch):
    import shutil as _shutil

    pre = _load_precommit()
    original_which = _shutil.which
    monkeypatch.setattr(_shutil, "which", lambda cmd: None if cmd == "bash" else original_which(cmd))
    (tmp_path / "script.sh").write_text("#!/bin/bash\necho hello\n")
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "bash" in msg
    assert "cannot verify" in msg


def test_precommit_missing_jq_blocks(tmp_path, monkeypatch):
    import shutil as _shutil

    pre = _load_precommit()
    original_which = _shutil.which
    monkeypatch.setattr(_shutil, "which", lambda cmd: None if cmd == "jq" else original_which(cmd))
    (tmp_path / "filter.jq").write_text("select(.x) !!BAD!!\n")
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "jq" in msg
    assert "cannot verify" in msg


# ── command class + real interpreters + advisory/error branches ──────────────


def test_precommit_command_md_missing_frontmatter_blocks(tmp_path):
    pre = _load_precommit()
    cmds = tmp_path / "commands"
    cmds.mkdir()
    (cmds / "do-thing.md").write_text("# no frontmatter here\n")
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "frontmatter" in msg


def test_precommit_valid_shell_passes(tmp_path):
    pre = _load_precommit()
    (tmp_path / "ok.sh").write_text("#!/bin/bash\necho hi\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_invalid_shell_blocks(tmp_path):
    pre = _load_precommit()
    (tmp_path / "bad.sh").write_text("#!/bin/bash\nif [ -z x ]; then\n")  # missing fi
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "syntax error" in msg


def test_precommit_valid_jq_passes(tmp_path):
    pre = _load_precommit()
    (tmp_path / "filter.jq").write_text(".x\n")
    verdict, _ = pre.run(tmp_path)
    assert verdict == "pass"


def test_precommit_invalid_jq_blocks(tmp_path):
    pre = _load_precommit()
    (tmp_path / "filter.jq").write_text("!!BAD!!\n")
    verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "jq parse fail" in msg


def test_precommit_shell_advisory_is_collected(tmp_path):
    pre = _load_precommit()
    (tmp_path / "ok.sh").write_text("#!/bin/bash\necho hi\n")
    with patch.object(pre, "_gate_shell", return_value=(None, "shell advisory")):
        verdict, msg = pre.run(tmp_path)
    assert verdict == "advise"
    assert "shell advisory" in msg


def test_precommit_jq_advisory_is_collected(tmp_path):
    pre = _load_precommit()
    (tmp_path / "filter.jq").write_text(".x\n")
    with patch.object(pre, "_gate_jq", return_value=(None, "jq advisory")):
        verdict, msg = pre.run(tmp_path)
    assert verdict == "advise"
    assert "jq advisory" in msg


def test_precommit_check_unknown_class_returns_empty(tmp_path):
    pre = _load_precommit()
    f = tmp_path / "x.txt"
    f.write_text("hi")
    blocks, advisories = pre._check(f, "mystery-class")
    assert blocks == []
    assert advisories == []


def test_precommit_read_error_becomes_block(tmp_path):
    pre = _load_precommit()
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "mentat-x.md").write_text("---\nname: x\n---\nbody\n")
    with patch.object(pre, "_check", side_effect=OSError("boom")):
        verdict, msg = pre.run(tmp_path)
    assert verdict == "block"
    assert "read error" in msg


# ── smells gate ──────────────────────────────────────────────────────────


def _load_smells():
    return load_script(_GATES / "smells.py", "smells_gate")


def test_smells_pass_on_clean_chunk(tmp_path):
    sm = _load_smells()
    (tmp_path / "ok.py").write_text("def f(x):\n    return x + 1\n")
    assert sm.run(tmp_path) == ("pass", "")


def test_smells_long_method_advises(tmp_path):
    sm = _load_smells()
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    (tmp_path / "big.py").write_text(f"def huge():\n{body}\n    return None\n")
    verdict, msg = sm.run(tmp_path)
    assert verdict == "advise"
    assert "long-method" in msg
    assert "huge" in msg


def test_smells_long_params_advises(tmp_path):
    sm = _load_smells()
    (tmp_path / "wide.py").write_text("def manyargs(a, b, c, d, e, f):\n    return None\n")
    verdict, msg = sm.run(tmp_path)
    assert verdict == "advise"
    assert "long-params" in msg


def test_smells_nested_conditional_advises(tmp_path):
    sm = _load_smells()
    src = (
        "def deep(x):\n"
        "    if x:\n"
        "        if x > 1:\n"
        "            for y in range(x):\n"
        "                while y:\n"
        "                    if y < 0:\n"
        "                        return y\n"
    )
    (tmp_path / "nest.py").write_text(src)
    verdict, msg = sm.run(tmp_path)
    assert verdict == "advise"
    assert "nested-conditional" in msg


def test_smells_syntax_error_skips_file(tmp_path):
    sm = _load_smells()
    (tmp_path / "broken.py").write_text("def bad(:::\n")
    (tmp_path / "ok.py").write_text("def f():\n    return 1\n")
    assert sm.run(tmp_path) == ("pass", "")


def test_smells_respects_env_tunables(tmp_path, monkeypatch):
    sm = _load_smells()
    monkeypatch.setenv("SMELL_LONG_METHOD_LINES", "5")
    body = "\n".join(f"    x{i} = {i}" for i in range(8))
    (tmp_path / "small.py").write_text(f"def medium():\n{body}\n")
    verdict, msg = sm.run(tmp_path)
    assert verdict == "advise"
    assert "long-method" in msg


def test_smells_pass_on_none(tmp_path):
    sm = _load_smells()
    assert sm.run(None) == ("pass", "")


def test_smells_skips_venv(tmp_path):
    sm = _load_smells()
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "huge.py").write_text(
        "def long():\n" + "\n".join(f"    x{i} = {i}" for i in range(50)) + "\n"
    )
    assert sm.run(tmp_path) == ("pass", "")


def test_smells_non_integer_env_tunable_falls_back_to_default(tmp_path, monkeypatch):
    sm = _load_smells()
    monkeypatch.setenv("SMELL_LONG_METHOD_LINES", "not-a-number")  # ValueError → default 30
    body = "\n".join(f"    x{i} = {i}" for i in range(35))
    (tmp_path / "big.py").write_text(f"def huge():\n{body}\n    return None\n")
    verdict, msg = sm.run(tmp_path)
    assert verdict == "advise"
    assert "long-method" in msg
