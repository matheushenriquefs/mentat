"""E2E: drive ``.agents/lib/style/lint.py`` through real-filesystem journeys.

Loads the free-standing linter script directly (for its table parser, classifier,
and per-file lint), then also runs it as a real subprocess for ``main``. Every
fixture is a real file on disk — a crafted STYLE.md voice-mapping table, real
SKILL.md / agent .md files under real directory names — never a mock. This
exercises ``_load_skill_voices`` brace-expansion and thin/full parsing,
``_classify`` for all four outcomes, each ``lint_file`` error branch, and the
three ``main`` exit paths.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
LINT_PY = REPO_ROOT / ".agents/lib/style/lint.py"

lint_mod = load_script(LINT_PY, "style_lint")

# Exit-code values are read from the same source the linter imports.
exits_mod = load_script(REPO_ROOT / ".agents/lib/exits.py", "style_lint_exits")
EX_OK = exits_mod.EX_OK
EX_FAILURE = exits_mod.EX_FAILURE
EX_USAGE = exits_mod.EX_USAGE


# --------------------------------------------------------------------------- #
# _load_skill_voices — the STYLE.md Voice-Mapping Table parser
# --------------------------------------------------------------------------- #


def _write_style_md(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "STYLE.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_skill_voices_parses_thin_full_and_brace_expansion(tmp_path):
    """A crafted table: a plain thin row, a plain full row, a braced full row that
    fans out to multiple names, plus header/divider/non-table rows that must be
    skipped, and a trailing ``#`` heading that ends the table."""
    style = _write_style_md(
        tmp_path,
        "\n".join(
            [
                "# Style",
                "",
                "## Voice-Mapping Table",
                "",
                "| Path pattern | Voice class | LOC budget |",
                "|---|---|---|",
                "| `.agents/skills/foo/SKILL.md` | Thin Skill | ≤40 |",
                "| `.agents/skills/bar/SKILL.md` | Full Skill | 75–120 |",
                "| `.agents/skills/cavecrew-{investigator,builder}/SKILL.md` | Full Skill |",
                "| not a table row, ignored |",
                "| `.agents/agents/mentat-*-reviewer.md` | Agent | 60–100 |",
                "| `docs/*.md` | Diátaxis (free) | n/a |",
                "",
                "## Next Section",
                "| `.agents/skills/after/SKILL.md` | Thin Skill | ≤40 |",
            ]
        ),
    )

    thin, full = lint_mod._load_skill_voices(style)

    # Plain thin row parsed; braced full row fanned out; agent/docs rows skipped
    # (regex requires a skills/<x>/SKILL path). "after" is past the closing "#".
    assert thin == {"foo"}
    assert full == {"bar", "cavecrew-investigator", "cavecrew-builder"}
    assert "after" not in thin and "after" not in full


def test_load_skill_voices_missing_file_returns_empty_sets(tmp_path):
    """The missing-file guard: a path that does not exist yields two empty sets."""
    missing = tmp_path / "does_not_exist" / "STYLE.md"
    assert not missing.exists()

    thin, full = lint_mod._load_skill_voices(missing)

    assert thin == set()
    assert full == set()


def test_load_skill_voices_unbraced_and_bad_brace_fall_through(tmp_path):
    """A skill name with a ``{`` but no matching ``{...}`` shape falls back to the
    raw name (the ``bm is None`` branch)."""
    style = _write_style_md(
        tmp_path,
        "\n".join(
            [
                "## Voice-Mapping Table",
                "|---|---|",
                "| `.agents/skills/weird{name/SKILL.md` | Thin Skill |",
            ]
        ),
    )

    thin, _full = lint_mod._load_skill_voices(style)

    assert thin == {"weird{name"}


# --------------------------------------------------------------------------- #
# _classify — thin / full / crew / None
# --------------------------------------------------------------------------- #


@pytest.fixture
def stub_voice_tables(monkeypatch):
    """Pin the module-global thin/full sets to known dir names so classification
    does not depend on the live repo STYLE.md."""
    monkeypatch.setattr(lint_mod, "_THIN", {"thin-skill"})
    monkeypatch.setattr(lint_mod, "_FULL", {"full-skill"})


def test_classify_thin_full_crew_and_none(tmp_path, stub_voice_tables):
    thin_file = tmp_path / "thin-skill" / "SKILL.md"
    full_file = tmp_path / "full-skill" / "SKILL.md"
    crew_file = tmp_path / ".agents" / "agents" / "mentat-x-reviewer.md"
    other_file = tmp_path / "unknown-skill" / "SKILL.md"
    non_skill = tmp_path / "thin-skill" / "README.md"

    assert lint_mod._classify(thin_file) == "thin"
    assert lint_mod._classify(full_file) == "full"
    assert lint_mod._classify(crew_file) == "crew"
    assert lint_mod._classify(other_file) is None
    assert lint_mod._classify(non_skill) is None


# --------------------------------------------------------------------------- #
# lint_file — each error branch
# --------------------------------------------------------------------------- #


def _skill(tmp_path: Path, dir_name: str, fm_lines: list[str], body_lines: list[str]) -> Path:
    d = tmp_path / dir_name
    d.mkdir(parents=True, exist_ok=True)
    path = d / "SKILL.md"
    content = "---\n" + "\n".join(fm_lines) + "\n---\n" + "\n".join(body_lines) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _agent(tmp_path: Path, fm_lines: list[str], body_lines: list[str]) -> Path:
    d = tmp_path / ".agents" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "mentat-x-reviewer.md"
    content = "---\n" + "\n".join(fm_lines) + "\n---\n" + "\n".join(body_lines) + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def test_lint_file_unclassified_returns_empty(tmp_path, stub_voice_tables):
    """A file that classifies to None short-circuits before any read of body."""
    path = _skill(tmp_path, "unknown-skill", ["name: x", "description: y"], ["body"])
    assert lint_mod.lint_file(path) == []


def test_lint_file_thin_missing_key_and_loc_overflow(tmp_path, stub_voice_tables):
    """Thin skill missing a required frontmatter key AND exceeding the 40 LOC cap."""
    body = [f"line {i}" for i in range(60)]  # well over 40 total LOC
    # Only `name` present → `description` is the missing required key.
    path = _skill(tmp_path, "thin-skill", ["name: t"], body)

    errs = lint_mod.lint_file(path)

    assert any("missing frontmatter key 'description'" in e for e in errs)
    assert any("thin skill" in e and "exceeds 40" in e for e in errs)


def test_lint_file_full_loc_out_of_range(tmp_path, stub_voice_tables):
    """Full skill with too few lines (< 75) trips the 75-120 range check."""
    path = _skill(tmp_path, "full-skill", ["name: f", "description: d"], ["short body"])

    errs = lint_mod.lint_file(path)

    assert any("full skill" in e and "not in" in e for e in errs)
    # Frontmatter complete → no missing-key error.
    assert not any("missing frontmatter key" in e for e in errs)


def test_lint_file_crew_loc_out_of_range_and_missing_tools(tmp_path, stub_voice_tables):
    """Crew agent missing the `tools` key AND out of the 60-100 LOC band."""
    path = _agent(tmp_path, ["name: a", "description: d"], ["Body fragment"])

    errs = lint_mod.lint_file(path)

    assert any("missing frontmatter key 'tools'" in e for e in errs)
    assert any("agent" in e and "not in 60" in e for e in errs)


def test_lint_file_banned_word_outside_fence_only(tmp_path, stub_voice_tables):
    """A banned word in prose is flagged, but the same word inside a ``` fenced
    block is stripped before scanning — proving fence removal works."""
    body = [
        "This is fine prose.",
        "```bash",
        "just run this simply",  # inside a fence → must NOT be flagged
        "```",
        "You should just do it.",  # in prose → must be flagged
    ]
    path = _skill(tmp_path, "full-skill", ["name: f", "description: d"], body)

    errs = lint_mod.lint_file(path)

    banned = [e for e in errs if "banned word/phrase" in e]
    assert len(banned) == 1, banned
    assert "'just'" in banned[0]


def test_lint_file_crew_article_hit(tmp_path, stub_voice_tables):
    """A crew agent body containing an article is flagged by ARTICLE_RE."""
    path = _agent(tmp_path, ["name: a", "description: d", "tools: [Read]"], ["Read the file."])

    errs = lint_mod.lint_file(path)

    assert any("agent must drop article" in e for e in errs)


def test_lint_file_clean_full_skill_has_no_errors(tmp_path, stub_voice_tables):
    """A well-formed full skill (75-120 LOC, complete frontmatter, no banned words)
    produces zero errors — the all-branches-pass path."""
    body = [f"content line {i}" for i in range(90)]  # 90 body lines → in 75-120
    path = _skill(tmp_path, "full-skill", ["name: f", "description: d"], body)

    assert lint_mod.lint_file(path) == []


# --------------------------------------------------------------------------- #
# main — real subprocess, three exit paths
# --------------------------------------------------------------------------- #


def _run_lint(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LINT_PY), *args],
        capture_output=True,
        text=True,
    )


def test_main_no_args_prints_usage(tmp_path):
    proc = _run_lint()
    assert proc.returncode == EX_USAGE
    assert "usage: lint.py" in proc.stderr


def test_main_clean_file_exits_ok(tmp_path):
    """A real full-skill SKILL.md under a dir name that the LIVE repo STYLE.md
    classifies as full — clean content → exit 0, no stderr."""
    d = tmp_path / "mentat-plan"  # 'mentat-plan' is a full skill in docs/STYLE.md
    d.mkdir()
    skill = d / "SKILL.md"
    body = "\n".join(f"content line {i}" for i in range(90))
    skill.write_text(f"---\nname: mentat-plan\ndescription: d\n---\n{body}\n", encoding="utf-8")

    proc = _run_lint(str(skill))

    assert proc.returncode == EX_OK, proc.stderr
    assert proc.stderr == ""


def test_main_violations_exit_failure_with_errors_on_stderr(tmp_path):
    """A real full-skill file with a banned word and bad LOC → exit EX_FAILURE and
    the errors printed on stderr."""
    d = tmp_path / "mentat-plan"
    d.mkdir()
    skill = d / "SKILL.md"
    # Too short for 75-120 and contains a banned word in prose.
    skill.write_text(
        "---\nname: mentat-plan\ndescription: d\n---\nYou should just do it.\n",
        encoding="utf-8",
    )

    proc = _run_lint(str(skill))

    assert proc.returncode == EX_FAILURE
    assert "banned word/phrase" in proc.stderr
    assert "full skill" in proc.stderr


def test_main_skips_non_file_args(tmp_path):
    """A path that is not a file is silently skipped (the ``p.is_file()`` guard),
    leaving no errors → exit 0."""
    missing = tmp_path / "nope.md"
    proc = _run_lint(str(missing))
    assert proc.returncode == EX_OK
    assert proc.stderr == ""


# --------------------------------------------------------------------------- #
# main — in-process (the subprocess variants above validate the real entrypoint,
# but a child process is not measured by the parent's `coverage run`, so these
# in-process calls are what drive main()'s branches into the coverage report).
# --------------------------------------------------------------------------- #


def test_main_in_process_no_args_returns_usage(capsys):
    assert lint_mod.main([]) == EX_USAGE
    assert "usage: lint.py" in capsys.readouterr().err


def test_main_in_process_clean_file_returns_ok(tmp_path, capsys):
    d = tmp_path / "mentat-plan"  # full skill per live docs/STYLE.md
    d.mkdir()
    skill = d / "SKILL.md"
    body = "\n".join(f"content line {i}" for i in range(90))
    skill.write_text(f"---\nname: mentat-plan\ndescription: d\n---\n{body}\n", encoding="utf-8")

    assert lint_mod.main([str(skill)]) == EX_OK
    assert capsys.readouterr().err == ""


def test_main_in_process_violations_return_failure(tmp_path, capsys):
    d = tmp_path / "mentat-plan"
    d.mkdir()
    skill = d / "SKILL.md"
    skill.write_text(
        "---\nname: mentat-plan\ndescription: d\n---\nYou should just do it.\n",
        encoding="utf-8",
    )

    assert lint_mod.main([str(skill)]) == EX_FAILURE
    assert "banned word/phrase" in capsys.readouterr().err


def test_main_in_process_skips_non_file(tmp_path, capsys):
    assert lint_mod.main([str(tmp_path / "nope.md")]) == EX_OK
    assert capsys.readouterr().err == ""
