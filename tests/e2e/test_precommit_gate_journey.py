"""E2E: drive the deterministic pre-commit gate over real fixture files.

Exercises ``lib.gates.code.precommit`` end to end — the file-class classifier,
each per-class gate, the ``_check`` dispatcher, the ``run`` walk, and the
``_PrecommitGate`` object — using real files on ``tmp_path`` with the path
shapes the classifier keys on. The only mocked boundaries are the external
interpreter seams (``shutil.which`` / ``subprocess.run``) so the bash/jq
branches run without requiring those tools on PATH, and one ``_check`` override
to force the ``OSError`` advisory branch inside ``run``.

Imported through the package (``from lib.gates.code import precommit``) because
the module uses package-relative imports; the repo's root ``conftest.py`` puts
``.agents`` on ``sys.path``, mirroring ``test_code_gates_journey.py``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _precommit_mod():
    from lib.gates.code import precommit

    return precommit


# ── _classify ────────────────────────────────────────────────────────────────


def test_classify_jsonc_suffix_is_unclassified(tmp_path: Path):
    # .jsonc is retired — no longer a special gate class.
    precommit = _precommit_mod()
    assert precommit._classify(tmp_path / "cfg.jsonc") is None


def test_classify_shell_suffix(tmp_path: Path):
    precommit = _precommit_mod()
    assert precommit._classify(tmp_path / "script.sh") == "shell"


def test_classify_jq_suffix(tmp_path: Path):
    precommit = _precommit_mod()
    assert precommit._classify(tmp_path / "filter.jq") == "jq"


def test_classify_context_md_is_workflow(tmp_path: Path):
    precommit = _precommit_mod()
    assert precommit._classify(tmp_path / "CONTEXT.md") == "workflow"


def test_classify_docs_adr_md_is_adr(tmp_path: Path):
    precommit = _precommit_mod()
    path = tmp_path / "docs" / "adr" / "0001-thing.md"
    assert precommit._classify(path) == "adr"


def test_classify_docs_adr_readme_is_not_adr(tmp_path: Path):
    precommit = _precommit_mod()
    path = tmp_path / "docs" / "adr" / "README.md"
    # README.md under docs/adr is explicitly excluded from the adr class.
    assert precommit._classify(path) is None


def test_classify_commands_md_is_command(tmp_path: Path):
    precommit = _precommit_mod()
    path = tmp_path / "commands" / "do-thing.md"
    assert precommit._classify(path) == "command"


def test_classify_skill_md_under_skills_is_skill(tmp_path: Path):
    precommit = _precommit_mod()
    path = tmp_path / "skills" / "my-skill" / "SKILL.md"
    assert precommit._classify(path) == "skill"


def test_classify_agents_md_doc_is_skill(tmp_path: Path):
    precommit = _precommit_mod()
    path = tmp_path / "agents" / "some-agent.md"
    assert precommit._classify(path) == "skill"


def test_classify_agents_root_agents_md_is_none(tmp_path: Path):
    precommit = _precommit_mod()
    path = tmp_path / "agents" / "AGENTS.md"
    assert precommit._classify(path) is None


def test_classify_unclassified_file_is_none(tmp_path: Path):
    precommit = _precommit_mod()
    assert precommit._classify(tmp_path / "foo.txt") is None


# ── _gate_adr ────────────────────────────────────────────────────────────────


def test_gate_adr_lists_missing_sections(tmp_path: Path):
    precommit = _precommit_mod()
    adr = tmp_path / "0001.md"
    # Present: Context. Missing: Decision + Consequences.
    adr.write_text("# ADR\n\n## Context\nsome context\n")
    msg = precommit._gate_adr(adr)
    assert msg is not None
    assert "## Decision" in msg
    assert "## Consequences" in msg
    assert "## Context" not in msg


def test_gate_adr_passes_when_all_sections_present(tmp_path: Path):
    precommit = _precommit_mod()
    adr = tmp_path / "0002.md"
    adr.write_text("## Context\na\n\n## Decision\nb\n\n## Consequences\nc\n")
    assert precommit._gate_adr(adr) is None


# ── _gate_frontmatter ────────────────────────────────────────────────────────


def test_gate_frontmatter_blocks_without_delimiter(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "SKILL.md"
    doc.write_text("# Heading\n\nno frontmatter here at all\n")
    msg = precommit._gate_frontmatter(doc)
    assert msg is not None
    assert "frontmatter" in msg


def test_gate_frontmatter_passes_with_delimiter(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "SKILL.md"
    doc.write_text("---\nname: x\n---\n\n# Body\n")
    assert precommit._gate_frontmatter(doc) is None


# ── _gate_workflow ───────────────────────────────────────────────────────────


def test_gate_workflow_blocks_without_link(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "CONTEXT.md"
    doc.write_text("# Context\n\nprose with no cross references\n")
    msg = precommit._gate_workflow(doc)
    assert msg is not None
    assert "cross-ref" in msg


def test_gate_workflow_passes_with_link(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "CONTEXT.md"
    doc.write_text("# Context\n\nsee [the plan](plan.md) for more\n")
    assert precommit._gate_workflow(doc) is None


# ── _gate_shell ──────────────────────────────────────────────────────────────


def test_gate_shell_blocks_when_bash_absent(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: None)
    doc = tmp_path / "s.sh"
    doc.write_text("echo hi\n")
    block, advise = precommit._gate_shell(doc)
    assert advise is None
    assert block is not None
    assert "bash not on PATH" in block


def test_gate_shell_passes_on_clean_syntax(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: "/bin/bash")
    monkeypatch.setattr(
        precommit.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stderr=""),
    )
    doc = tmp_path / "s.sh"
    doc.write_text("echo hi\n")
    assert precommit._gate_shell(doc) == (None, None)


def test_gate_shell_blocks_on_syntax_error(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: "/bin/bash")
    monkeypatch.setattr(
        precommit.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=2, stderr="unexpected EOF"),
    )
    doc = tmp_path / "s.sh"
    doc.write_text("if true; then\n")
    block, advise = precommit._gate_shell(doc)
    assert advise is None
    assert block is not None
    assert "bash -n syntax error" in block
    assert "unexpected EOF" in block


# ── _gate_jq ─────────────────────────────────────────────────────────────────


def test_gate_jq_blocks_when_jq_absent(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: None)
    doc = tmp_path / "f.jq"
    doc.write_text(".a\n")
    block, advise = precommit._gate_jq(doc)
    assert advise is None
    assert block is not None
    assert "jq not on PATH" in block


def test_gate_jq_passes_on_clean_filter(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: "/usr/bin/jq")
    monkeypatch.setattr(
        precommit.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stderr=""),
    )
    doc = tmp_path / "f.jq"
    doc.write_text(".a\n")
    assert precommit._gate_jq(doc) == (None, None)


def test_gate_jq_blocks_on_parse_error(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: "/usr/bin/jq")
    monkeypatch.setattr(
        precommit.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=3, stderr="syntax error"),
    )
    doc = tmp_path / "f.jq"
    doc.write_text("...garbage\n")
    block, advise = precommit._gate_jq(doc)
    assert advise is None
    assert block is not None
    assert "jq parse fail" in block
    assert "syntax error" in block


# ── _check dispatcher ────────────────────────────────────────────────────────


def test_check_skill_blocks_on_missing_frontmatter(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "SKILL.md"
    doc.write_text("# no frontmatter\n")
    blocks, advisories = precommit._check(doc, "skill")
    assert advisories == []
    assert len(blocks) == 1
    assert "frontmatter" in blocks[0]


def test_check_command_passes_with_frontmatter(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "cmd.md"
    doc.write_text("---\nx: 1\n---\nbody\n")
    assert precommit._check(doc, "command") == ([], [])


def test_check_adr_blocks_on_missing_sections(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "0001.md"
    doc.write_text("## Context\nonly this\n")
    blocks, advisories = precommit._check(doc, "adr")
    assert advisories == []
    assert len(blocks) == 1


def test_check_adr_passes_when_complete(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "0001.md"
    doc.write_text("## Context\na\n## Decision\nb\n## Consequences\nc\n")
    assert precommit._check(doc, "adr") == ([], [])


def test_check_workflow_blocks_without_link(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "CONTEXT.md"
    doc.write_text("no links\n")
    blocks, advisories = precommit._check(doc, "workflow")
    assert advisories == []
    assert len(blocks) == 1


def test_check_workflow_passes_with_link(tmp_path: Path):
    precommit = _precommit_mod()
    doc = tmp_path / "CONTEXT.md"
    doc.write_text("see [x](y.md)\n")
    assert precommit._check(doc, "workflow") == ([], [])


def test_check_shell_blocks_when_absent(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: None)
    doc = tmp_path / "s.sh"
    doc.write_text("echo hi\n")
    blocks, advisories = precommit._check(doc, "shell")
    assert advisories == []
    assert len(blocks) == 1
    assert "bash not on PATH" in blocks[0]


def test_check_shell_passes_when_clean(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: "/bin/bash")
    monkeypatch.setattr(
        precommit.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stderr=""),
    )
    doc = tmp_path / "s.sh"
    doc.write_text("echo hi\n")
    assert precommit._check(doc, "shell") == ([], [])


def test_check_jq_blocks_when_absent(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: None)
    doc = tmp_path / "f.jq"
    doc.write_text(".a\n")
    blocks, advisories = precommit._check(doc, "jq")
    assert advisories == []
    assert len(blocks) == 1
    assert "jq not on PATH" in blocks[0]


def test_check_jq_passes_when_clean(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: "/usr/bin/jq")
    monkeypatch.setattr(
        precommit.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stderr=""),
    )
    doc = tmp_path / "f.jq"
    doc.write_text(".a\n")
    assert precommit._check(doc, "jq") == ([], [])


# ── run ──────────────────────────────────────────────────────────────────────


def test_run_pass_on_none():
    precommit = _precommit_mod()
    verdict, msg = precommit.run(None)
    assert verdict == "block"
    assert "no chunk path" in msg


def test_run_blocks_on_nonexistent_path(tmp_path: Path):
    precommit = _precommit_mod()
    verdict, msg = precommit.run(tmp_path / "nope")
    assert verdict == "block"
    assert "missing" in msg


def test_run_blocks_on_bad_classified_file(tmp_path: Path):
    precommit = _precommit_mod()
    skill_dir = tmp_path / "skills" / "widget"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# missing frontmatter\n")
    verdict, msg = precommit.run(tmp_path)
    assert verdict == "block"
    assert "frontmatter" in msg


def test_run_passes_on_clean_classified_files(tmp_path: Path):
    precommit = _precommit_mod()
    skill_dir = tmp_path / "skills" / "widget"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: widget\n---\nbody\n")
    assert precommit.run(tmp_path) == ("pass", "")


def test_run_skips_unclassified_files(tmp_path: Path):
    precommit = _precommit_mod()
    # Only unclassified files present → nothing checked → pass.
    (tmp_path / "readme.txt").write_text("just text\n")
    (tmp_path / "data.bin").write_text("blob\n")
    assert precommit.run(tmp_path) == ("pass", "")


def test_run_blocks_on_oserror(tmp_path: Path, monkeypatch):
    precommit = _precommit_mod()
    skill_dir = tmp_path / "skills" / "widget"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: widget\n---\nbody\n")

    def _boom(_path, _cls):
        raise OSError("disk gone")

    monkeypatch.setattr(precommit, "_check", _boom)
    verdict, msg = precommit.run(tmp_path)
    assert verdict == "block"
    assert "read error" in msg
    assert "disk gone" in msg


def test_run_on_single_file_uses_parent_dir(tmp_path: Path):
    precommit = _precommit_mod()
    skill_dir = tmp_path / "skills" / "widget"
    skill_dir.mkdir(parents=True)
    target = skill_dir / "SKILL.md"
    target.write_text("# missing frontmatter\n")
    # Passing the file itself → root resolves to its parent dir.
    verdict, msg = precommit.run(target)
    assert verdict == "block"
    assert "frontmatter" in msg


# ── _PrecommitGate ───────────────────────────────────────────────────────────


def test_gate_identity():
    precommit = _precommit_mod()
    assert precommit.gate.id == "precommit"
    assert precommit.gate.priority == 10


def test_gate_run_delegates_to_run(tmp_path: Path):
    precommit = _precommit_mod()
    skill_dir = tmp_path / "skills" / "widget"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# missing frontmatter\n")
    ctx = SimpleNamespace(chunk_path=tmp_path)
    verdict, msg = precommit.gate.run(ctx)
    assert verdict == "block"
    assert "frontmatter" in msg


def test_gate_run_blocks_on_ctx_without_chunk_path():
    precommit = _precommit_mod()

    class _Bare:
        pass

    verdict, msg = precommit.gate.run(_Bare())
    assert verdict == "block"
    assert "no chunk path" in msg
