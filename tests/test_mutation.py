"""Advisory mutation runner (CS1) — pure scoping, key-mapping, and report helpers.

`tasks/` is dev tooling, out of the coverage gate; these tests pin the runner's
deterministic core (the subprocess shell is exercised via the marker path only).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _mutation_mod():
    spec = importlib.util.spec_from_file_location("mutation_task", ROOT / "tasks" / "mutation.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── coverage_source_prefixes ─────────────────────────────────────────────────


def test_coverage_source_prefixes_reads_pyproject():
    m = _mutation_mod()
    text = '[tool.coverage.run]\nsource = [".agents/lib", ".agents/skills"]\n'
    assert m.coverage_source_prefixes(text) == (".agents/lib/", ".agents/skills/")


def test_coverage_source_prefixes_absent_is_empty():
    m = _mutation_mod()
    assert m.coverage_source_prefixes("[tool.other]\nx = 1\n") == ()


def test_coverage_source_prefixes_matches_real_pyproject():
    """The runner's shipped-source set must track the coverage gate's, not drift."""
    m = _mutation_mod()
    prefixes = m.coverage_source_prefixes((ROOT / "pyproject.toml").read_text())
    assert ".agents/lib/" in prefixes
    assert ".agents/skills/" in prefixes


# ── select_targets ───────────────────────────────────────────────────────────


def test_select_targets_keeps_shipped_source_py():
    m = _mutation_mod()
    changed = [".agents/lib/gates/score.py", ".agents/skills/x/scripts/y.py"]
    assert m.select_targets(changed, (".agents/lib/", ".agents/skills/")) == changed


def test_select_targets_drops_tests_and_nonpy_and_offsource():
    m = _mutation_mod()
    changed = [
        "tests/test_score.py",  # test file
        ".agents/lib/gates/score.py",  # kept
        "pyproject.toml",  # non-py
        "docs/adr/0016.md",  # off-source
        "tasks/mutation.py",  # off-source (dev tooling, not shipped)
    ]
    assert m.select_targets(changed, (".agents/lib/", ".agents/skills/")) == [".agents/lib/gates/score.py"]


def test_select_targets_sorted_and_deduped():
    m = _mutation_mod()
    changed = [".agents/lib/b.py", ".agents/lib/a.py", ".agents/lib/b.py"]
    assert m.select_targets(changed, (".agents/lib/",)) == [".agents/lib/a.py", ".agents/lib/b.py"]


def test_select_targets_empty_when_no_shipped_source_touched():
    m = _mutation_mod()
    assert m.select_targets(["README.md", "tests/test_x.py"], (".agents/lib/",)) == []


# ── module_of / mutant_patterns ──────────────────────────────────────────────


def test_module_of_dots_the_path():
    m = _mutation_mod()
    assert m.module_of(".agents/lib/gates/score.py") == ".agents.lib.gates.score"


def test_module_of_strips_src_prefix():
    m = _mutation_mod()
    assert m.module_of("src/pkg/mod.py") == "pkg.mod"


def test_mutant_patterns_globs_each_target():
    m = _mutation_mod()
    assert m.mutant_patterns([".agents/lib/gates/score.py"]) == [".agents.lib.gates.score.*"]


# ── survivor_keys ────────────────────────────────────────────────────────────


def test_survivor_keys_selects_only_survived():
    m = _mutation_mod()
    text = (
        "    .agents.lib.gates.score.x_score_test__mutmut_1: survived\n"
        "    .agents.lib.gates.score.x_score_test__mutmut_2: killed\n"
        "    .agents.lib.gates.verdict.x__coerce_veto__mutmut_3: survived\n"
    )
    assert m.survivor_keys(text) == [
        ".agents.lib.gates.score.x_score_test__mutmut_1",
        ".agents.lib.gates.verdict.x__coerce_veto__mutmut_3",
    ]


def test_survivor_keys_empty_when_all_killed():
    m = _mutation_mod()
    assert m.survivor_keys("    a.b.x_f__mutmut_1: killed\n") == []


# ── key_to_location ──────────────────────────────────────────────────────────


def test_key_to_location_maps_function_to_def_line():
    m = _mutation_mod()
    targets = [".agents/lib/gates/score.py"]
    src = {".agents/lib/gates/score.py": ["import x", "", "def score_test(raw):", "    return 1"]}
    key = ".agents.lib.gates.score.x_score_test__mutmut_4"
    loc = m.key_to_location(key, targets, lines_of=lambda p: src[p])
    assert loc == ".agents/lib/gates/score.py:3"


def test_key_to_location_handles_method_separator():
    m = _mutation_mod()
    targets = [".agents/lib/gates/verdict.py"]
    src = {".agents/lib/gates/verdict.py": ["class ReviewVerdict:", "    def from_raw(cls, raw):", "        return 1"]}
    key = f".agents.lib.gates.verdict.x{m.CLASS_NAME_SEPARATOR}ReviewVerdict{m.CLASS_NAME_SEPARATOR}from_raw__mutmut_1"
    assert m.key_to_location(key, targets, lines_of=lambda p: src[p]) == ".agents/lib/gates/verdict.py:2"


def test_key_to_location_unknown_def_line_falls_back_to_question():
    m = _mutation_mod()
    targets = [".agents/lib/gates/score.py"]
    key = ".agents.lib.gates.score.x_missing__mutmut_1"
    assert m.key_to_location(key, targets, lines_of=lambda p: ["x = 1"]) == ".agents/lib/gates/score.py:?"


def test_key_to_location_no_matching_target_returns_key():
    m = _mutation_mod()
    key = "other.module.x_f__mutmut_1"
    assert m.key_to_location(key, [".agents/lib/gates/score.py"], lines_of=lambda p: []) == key


def test_locate_survivors_sorted_deduped():
    m = _mutation_mod()
    targets = [".agents/lib/a.py"]
    src = {".agents/lib/a.py": ["def f():", "    pass", "def g():", "    pass"]}
    keys = [
        ".agents.lib.a.x_g__mutmut_2",
        ".agents.lib.a.x_f__mutmut_1",
        ".agents.lib.a.x_f__mutmut_9",  # same def line as x_f__mutmut_1 → deduped
    ]
    assert m.locate_survivors(keys, targets, lines_of=lambda p: src[p]) == [
        ".agents/lib/a.py:1",
        ".agents/lib/a.py:3",
    ]


# ── format_report ────────────────────────────────────────────────────────────


def test_format_report_clean():
    m = _mutation_mod()
    assert "no surviving mutants" in m.format_report([])


def test_format_report_lists_locations_with_count():
    m = _mutation_mod()
    report = m.format_report([".agents/lib/a.py:1", ".agents/lib/a.py:3"])
    assert "2 surviving mutant(s)" in report
    assert ".agents/lib/a.py:1" in report
    assert ".agents/lib/a.py:3" in report


# ── run marker path (no mutmut invocation) ───────────────────────────────────


def test_run_changed_no_targets_prints_marker(capsys, monkeypatch):
    m = _mutation_mod()
    monkeypatch.setattr(m, "changed_files", lambda base: ["README.md"])
    rc = m.run(changed_only=True, base="main")
    assert rc == 0
    assert "nothing to mutate" in capsys.readouterr().out


def test_run_changed_no_targets_is_stable_across_two_runs(capsys, monkeypatch):
    m = _mutation_mod()
    monkeypatch.setattr(m, "changed_files", lambda base: ["docs/x.md", "tests/test_y.py"])
    m.run(changed_only=True, base="main")
    first = capsys.readouterr().out
    m.run(changed_only=True, base="main")
    second = capsys.readouterr().out
    assert first == second
