"""Tests for .agents/lib/style/lint.py — Tier-1 style linter."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tests.conftest import load_script

LIB = Path(__file__).resolve().parents[1] / ".agents/lib/style/lint.py"

lint = load_script(LIB, "lint")


def _thin_skill(tmp_path: Path, content: str) -> Path:
    d = tmp_path / ".agents" / "skills" / "mentat-install"
    d.mkdir(parents=True)
    p = d / "SKILL.md"
    p.write_text(content)
    return p


def _full_skill(tmp_path: Path, content: str) -> Path:
    d = tmp_path / ".agents" / "skills" / "mentat-implement"
    d.mkdir(parents=True)
    p = d / "SKILL.md"
    p.write_text(content)
    return p


def _crew_agent(tmp_path: Path, content: str) -> Path:
    d = tmp_path / ".agents" / "agents"
    d.mkdir(parents=True)
    p = d / "mentat-test-reviewer.md"
    p.write_text(content)
    return p


CLEAN_THIN = textwrap.dedent("""\
    ---
    name: mentat-install
    description: Install mentat skills into the devcontainer. Use when bootstrapping.
    ---

    1. Run `python3 ~/.agents/skills/mentat-install/scripts/install.py`.
    2. Done.
""")

CLEAN_FULL = textwrap.dedent("""\
    ---
    name: mentat-implement
    description: Execute a plan slice-by-slice with TDD and gates. Use when implementing a plan.
    ---

    # mentat-implement

    Atomic single-plan executor. One job: execute one plan in the calling session.

    ## Phase 1 — Preflight

    Read plan frontmatter: id, class. Emit `chunk_started` event. Check container is up.
    Derive artifact predicates from slice list. Refuse DONE slices.
    Exit 66 if plan slug not found. Exit 78 if config missing. Exit 69 if container down.

    ## Phase 2 — TDD Loop

    For each pending slice:

    1. Write a failing test (red). Commit the test.
    2. Implement until green. Do not touch the test.
    3. Run the gate. Any veto → fix, re-commit.
    4. Commit the slice via `/mentat-commit`.

    If AFK class and ambiguity detected in session JSONL → emit `chunk_ejected`, exit 42.

    ## Phase 3 — Gate

    Spawn reviewers in parallel:
    - `mentat-plan-reviewer` — plan alignment ≥ 0.88.
    - `mentat-bug-reviewer` — no latent bugs sev≥high.
    - `mentat-test-reviewer` — test-plan alignment ≥ 0.88.
    - `mentat-smell-reviewer` — no hard-tier smells.

    Any veto or threshold fail → emit `gate_evaluated`, fix cited miss, re-commit, re-spawn.
    No rebase on gate fail. All reviewer verdicts logged via `/mentat-log emit`.
    Each `review_submitted` event carries reviewer slug, score, threshold, verdict.

    ## Phase 4 — Commit

    Commit via `/mentat-commit`. One commit per slice. No squash.
    Rebase onto holding branch via `/mentat-rebase`.
    Emit `chunk_landed` with sha + holding branch after successful fast-forward.

    ## Phase 5 — Cleanup

    Tear down container. Emit `agent_stopped` event.
    If any slice failed: emit `chunk_ejected` with reason, path before exit.
    Exit 0 on success. Exit 1 on gate or TDD failure.

    ## Rules

    - Never skip slices; verify artifacts on disk before marking done.
    - Container required (ADR-0004). Exit 69 if container down.
    - AFK class forbids `AskUserQuestion`; ambiguity → emit `chunk_ejected`, exit 42.
    - Stale-ref sweep required after any rename before commit.
    - One commit per slice. No squash at end of plan.
    - Gate verdicts are final per run; re-run gate after any fix.
    - Read-only test mount enforced per `<slug>.tests.json` manifest (ADR-0006).

    ## Constraints

    - HITL class: `AskUserQuestion` allowed at any phase.
    - AFK class: no interactive prompts; ambiguity is ejection, not a question.
    - Harness selection from `~/.mentat/config.toml`; `--harness` flag overrides.
    - Plan class read from frontmatter only; no env var override.
    - Session id from `$MENTAT_SESSION` (`<epoch>-<pid>` format).
    - Log dir created mode 0o700 on first write.
    - All emit calls route through `/mentat-log emit`; no skill writes JSONL directly.

    ## Entry Point

    ```
    python3 ~/.agents/skills/mentat-implement/scripts/implement.py <plan-slug>
    ```

    Plan slug resolves under `~/.agents/plans/`. Absolute path also accepted.
    Multi-slug input → exit 64; use `/mentat-orchestrate` for multi-plan dispatch.
""")

CLEAN_CREW = textwrap.dedent("""\
    ---
    name: mentat-test-reviewer
    description: Read-only test-faithfulness reviewer. Scores whether tests assert plan intent and whether impl earns green or games it. Deterministic veto on gamed green. Refuses to edit, run, or rebase.
    tools: [Read, Grep, Glob]
    ---

    ## Job

    Score tests against plan behaviors. Veto on gamed green.
    Plan behaviors = context. Test assertions = claims. Catch green-but-wrong.

    ## Three Lenses

    - **Intent lens** — do tests assert planned behaviors?
    - **Assertion lens** — are assertions meaningful, not trivially true?
    - **Gaming lens** — did impl disable/delete assertions to pass?

    ## Blacklist

    Any hit → veto (score 0.0), no averaging:

    - Delete or empty assertion block.
    - Monkey-patch production path to skip real behavior.
    - `assert True` or unconditional pass added to test body.
    - `pytest.skip` added inside impl loop (not pre-existing).

    ## Output

    ```
    PASS | FAIL  asserts_plan=<0.00–1.00>  veto=<clean|tripped:reason>
    <≤3 lines: untested intent, weak assertion, deleted assertion — file:line>
    ```

    Score below 0.88 → FAIL. Veto regardless of score.

    ## Refusals

    Asked to edit → Read-only. Return findings only.
    Asked for score on non-plan input → Not checkable. Return empty findings.
    Asked to run tests → Spawn cavecrew-builder.

    ## Scoring

    Score formula: `asserts_plan = matched_behaviors / total_plan_behaviors`.
    Threshold: 0.88. Below → FAIL regardless of veto status.
    Veto always overrides score: veto-tripped chunk scores 0.0 regardless.

    ## Scope

    Read test files listed in `closed` + `open` arrays from `<slug>.tests.json`.
    Read plan slice section for planned behaviors.
    Do not read impl files — scoring is test-vs-plan, not test-vs-impl.

    ## Limits

    Report ≤3 findings per lens. Flag highest-severity first.
    Return empty findings array on plan-less input, not error.
    Coverage gap below threshold = weak-assertion finding, not veto.

    ## Notes

    Keep this reviewer read-only. Never edit tests or implementation files.
    Never run pytest or rebase branches from this role.
    Report findings only; implementer owns fixes.
    Veto triggers only on blacklist patterns above.
    Empty findings array on plan-less input, not error.
    Coverage gap below threshold = weak-assertion finding, not veto.
""")


# ── classify ──────────────────────────────────────────────────────────────────


def test_classify_thin_skill(tmp_path):
    p = _thin_skill(tmp_path, CLEAN_THIN)
    assert lint._classify(p) == "thin"


def test_classify_full_skill(tmp_path):
    p = _full_skill(tmp_path, CLEAN_FULL)
    assert lint._classify(p) == "full"


def test_classify_crew(tmp_path):
    p = _crew_agent(tmp_path, CLEAN_CREW)
    assert lint._classify(p) == "crew"


def test_classify_unknown_returns_none(tmp_path):
    p = tmp_path / "README.md"
    p.write_text("hello")
    assert lint._classify(p) is None


# ── clean files pass ──────────────────────────────────────────────────────────


def test_clean_thin_passes(tmp_path):
    p = _thin_skill(tmp_path, CLEAN_THIN)
    assert lint.lint_file(p) == []


def test_clean_full_passes(tmp_path):
    p = _full_skill(tmp_path, CLEAN_FULL)
    assert lint.lint_file(p) == []


def test_clean_crew_passes(tmp_path):
    p = _crew_agent(tmp_path, CLEAN_CREW)
    assert lint.lint_file(p) == []


# ── LOC budget ────────────────────────────────────────────────────────────────


def test_thin_loc_overflow(tmp_path):
    fat = CLEAN_THIN + "\n" * 50
    p = _thin_skill(tmp_path, fat)
    errs = lint.lint_file(p)
    assert any("LOC exceeds 40" in e for e in errs)


def test_full_loc_too_short(tmp_path):
    short = CLEAN_FULL.splitlines()[:20]
    p = _full_skill(tmp_path, "\n".join(short))
    errs = lint.lint_file(p)
    assert any("not in 75" in e for e in errs)


def test_full_loc_too_long(tmp_path):
    fat = CLEAN_FULL + "\n" * 120
    p = _full_skill(tmp_path, fat)
    errs = lint.lint_file(p)
    assert any("not in 75" in e for e in errs)


def test_crew_loc_too_short(tmp_path):
    short = CLEAN_CREW.splitlines()[:20]
    p = _crew_agent(tmp_path, "\n".join(short))
    errs = lint.lint_file(p)
    assert any("not in 60" in e for e in errs)


def test_crew_loc_too_long(tmp_path):
    fat = CLEAN_CREW + "\n" * 80
    p = _crew_agent(tmp_path, fat)
    errs = lint.lint_file(p)
    assert any("not in 60" in e for e in errs)


# ── banned words ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("word", ["just", "simply", "really", "basically", "actually", "obviously"])
def test_banned_word_thin(tmp_path, word):
    body = CLEAN_THIN + f"\nNote: {word} run this step.\n"
    p = _thin_skill(tmp_path, body)
    errs = lint.lint_file(p)
    assert any(word in e for e in errs), f"expected '{word}' to be flagged"


@pytest.mark.parametrize("word", ["just", "simply", "really", "basically", "actually", "obviously"])
def test_banned_word_full(tmp_path, word):
    body = CLEAN_FULL + f"\nNote: {word} do this step.\n"
    p = _full_skill(tmp_path, body)
    errs = lint.lint_file(p)
    assert any(word in e for e in errs), f"expected '{word}' to be flagged"


def test_banned_word_in_code_fence_skipped(tmp_path):
    body = CLEAN_THIN + "\n```bash\n# just run this\n```\n"
    p = _thin_skill(tmp_path, body)
    errs = lint.lint_file(p)
    assert not any("just" in e for e in errs)


# ── frontmatter keys ──────────────────────────────────────────────────────────


def test_crew_missing_tools_key(tmp_path):
    no_tools = CLEAN_CREW.replace("tools: [Read, Grep, Glob]\n", "")
    p = _crew_agent(tmp_path, no_tools)
    errs = lint.lint_file(p)
    assert any("tools" in e for e in errs)


def test_thin_missing_name_key(tmp_path):
    no_name = CLEAN_THIN.replace("name: mentat-install\n", "")
    p = _thin_skill(tmp_path, no_name)
    errs = lint.lint_file(p)
    assert any("'name'" in e for e in errs)


# ── article drop (crew only) ──────────────────────────────────────────────────


def test_crew_article_flagged(tmp_path):
    body = CLEAN_CREW + "\nThis is a finding.\n"
    p = _crew_agent(tmp_path, body)
    errs = lint.lint_file(p)
    assert any("article" in e for e in errs)


def test_thin_article_not_flagged(tmp_path):
    body = CLEAN_THIN + "\nThis is a description.\n"
    p = _thin_skill(tmp_path, body)
    errs = lint.lint_file(p)
    assert not any("article" in e for e in errs)


# ── CLI ────────────────────────────────────────────────────────────────────────


def test_main_no_args_returns_64():
    assert lint.main([]) == 64


def test_main_clean_file_returns_0(tmp_path):
    p = _thin_skill(tmp_path, CLEAN_THIN)
    assert lint.main([str(p)]) == 0


def test_main_violation_returns_1(tmp_path):
    body = CLEAN_THIN + "\n" * 50
    p = _thin_skill(tmp_path, body)
    assert lint.main([str(p)]) == 1


def test_main_skips_non_file_args(tmp_path):
    # A path that is not a file → the `if p.is_file()` guard skips it (138->136).
    assert lint.main([str(tmp_path / "does-not-exist.md")]) == 0


# ── _load_skill_voices table parsing ────────────────────────────────────────


_VOICE_TABLE = textwrap.dedent("""\
    # Preamble heading

    ## Voice-Mapping Table

    | Path pattern | Voice |
    | --- | --- |
    | `skills/mentat-foo/SKILL.md` | thin |
    | `skills/mentat-bar/SKILL.md` | full |
    | `skills/mentat-{a,b}/SKILL.md` | thin |
    | `skills/mentat-brace{/SKILL.md` | full |
    | `skills/mentat-baz/SKILL.md` | medium |
    | onlyonecol |
    | `no-skill-pattern-here` | thin |

    plain trailing prose, no heading
""")


def test_load_skill_voices_missing_file_returns_empty(tmp_path):
    thin, full = lint._load_skill_voices(tmp_path / "no-such-STYLE.md")
    assert thin == set()
    assert full == set()


def test_load_skill_voices_parses_table_variants(tmp_path):
    style = tmp_path / "STYLE.md"
    style.write_text(_VOICE_TABLE)
    thin, full = lint._load_skill_voices(style)
    # brace expansion → mentat-a, mentat-b; plain thin → mentat-foo
    assert {"mentat-foo", "mentat-a", "mentat-b"} <= thin
    # plain full → mentat-bar; unmatched-brace kept raw → mentat-brace{
    assert "mentat-bar" in full
    assert "mentat-brace{" in full
    # medium voice → neither set; malformed rows ignored
    assert "mentat-baz" not in thin
    assert "mentat-baz" not in full


def test_load_skill_voices_breaks_on_next_heading(tmp_path):
    # A `#` heading after the table breaks the loop early (covers the break arc).
    style = tmp_path / "STYLE.md"
    style.write_text(
        "## Voice-Mapping Table\n\n"
        "| Path pattern | Voice |\n| --- | --- |\n"
        "| `skills/mentat-foo/SKILL.md` | thin |\n"
        "# Next Section\n"
        "| `skills/mentat-after/SKILL.md` | full |\n"
    )
    thin, full = lint._load_skill_voices(style)
    assert "mentat-foo" in thin
    assert "mentat-after" not in full  # after the break, not parsed


def test_classify_skill_md_unknown_parent_returns_none(tmp_path):
    # SKILL.md whose parent dir is neither thin nor full → falls through to None.
    d = tmp_path / ".agents" / "skills" / "not-a-known-skill"
    d.mkdir(parents=True)
    p = d / "SKILL.md"
    p.write_text("---\nname: x\n---\nbody\n")
    assert lint._classify(p) is None


def test_lint_file_unclassified_returns_empty(tmp_path):
    p = tmp_path / "random.md"
    p.write_text("just some prose\n")
    assert lint.lint_file(p) == []


def test_lint_module_inserts_lib_on_sys_path(monkeypatch):
    import sys

    parent = str(lint._LIB)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != parent])
    reloaded = load_script(LIB, "lint_reload")  # re-exec bootstrap with parent absent
    assert str(reloaded._LIB) in sys.path
