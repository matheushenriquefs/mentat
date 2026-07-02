"""E2E: drive the code-gate stack over real fixture file trees on tmp_path.

Exercises the shared file walk (``lib.gates._walk``), the gate engine's
priority-sort + short-circuit dispatch (``lib.gates.engine``), and the
deterministic smell detector (``lib.gates.code.smells``) end to end — real
directories, real ``.py`` sources parsed by the stdlib ``ast`` module, no
mocking of the modules under test. The one exception is the engine dispatch
test, which injects tiny fake Gate objects via the ``_gates=`` seam so the
sort-by-priority and stop-on-first-block logic is exercised deterministically.

Imports go through the package (``import lib.gates.engine``) rather than
``load_script`` because these modules use relative / package imports
(``from lib.gates.code import ...``); the repo's root ``conftest.py`` puts
``.agents`` on ``sys.path``, mirroring ``tests/test_engine.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]


def _walk_mod():
    from lib.gates import _walk

    return _walk


def _engine_mod():
    from lib.gates import engine

    return engine


def _smells_mod():
    from lib.gates.code import smells

    return smells


# ── _walk.iter_files: real tree, SKIP_DIRS pruned, non-files skipped ─────────
# Targets .agents/lib/gates/_walk.py lines 25-30 (rglob loop, is_file continue,
# SKIP_DIRS membership continue, yield).


def test_iter_files_yields_real_files_and_skips_skipdirs(tmp_path: Path):
    walk = _walk_mod()

    # Real files that must be yielded.
    (tmp_path / "top.py").write_text("x = 1\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("hi\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("y = 2\n")

    # A plain subdirectory with no file of its own → hits the ``is_file()``
    # continue for the directory entry itself.
    (tmp_path / "emptydir").mkdir()

    # One file buried under each SKIP_DIRS entry — all must be pruned.
    for skip in (".git", "__pycache__", "node_modules", ".venv", ".mentat"):
        d = tmp_path / skip / "nested"
        d.mkdir(parents=True)
        (d / "buried.py").write_text("z = 3\n")

    found = {p.relative_to(tmp_path).as_posix() for p in walk.iter_files(tmp_path)}

    assert found == {"top.py", "docs/README.md", "pkg/mod.py"}, found
    # Nothing under a SKIP_DIRS directory leaked through.
    assert not any(part in walk.SKIP_DIRS for p in walk.iter_files(tmp_path) for part in p.parts)


# ── engine.evaluate: real gates over real trees (pass + block) ───────────────
# Targets .agents/lib/gates/engine.py lines 35-41 (sort, GateContext build,
# loop, block short-circuit return, pass return) with the REAL _GATES.


def test_evaluate_pass_on_clean_tree_with_real_gates(tmp_path: Path):
    engine = _engine_mod()

    # Clean, well-formed sources: nothing the precommit or smells gate flags,
    # and no file classes precommit blocks on.
    (tmp_path / "clean.py").write_text("def f(x):\n    return x + 1\n")
    (tmp_path / "notes.txt").write_text("just prose\n")

    verdict, msg = engine.evaluate(tmp_path)
    assert verdict == "pass"
    assert msg == ""


def test_evaluate_blocks_on_tree_that_trips_a_real_gate(tmp_path: Path):
    engine = _engine_mod()

    # An ADR missing the mandatory ## Consequences section trips the real
    # precommit gate → the engine must surface a ("block", msg).
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-foo.md").write_text("# ADR 0001\n\n## Context\nx\n\n## Decision\ny\n")

    verdict, msg = engine.evaluate(tmp_path)
    assert verdict == "block"
    assert "Consequences" in msg


# ── engine.evaluate: injected fake gates exercise sort + short-circuit ───────
# Targets engine.py line 35 (sorted by priority) and lines 38-40 (loop,
# per-gate run, return on first block).


class _RecordingGate:
    """Minimal Gate: records invocation order, returns a canned verdict."""

    def __init__(self, gate_id: str, priority: int, verdict: str, log: list[str]):
        self.id = gate_id
        self.priority = priority
        self._verdict = verdict
        self._log = log

    def run(self, ctx: object) -> tuple[str, str]:
        self._log.append(self.id)
        # Confirm the engine handed us a real GateContext carrying chunk_path.
        assert hasattr(ctx, "chunk_path")
        return (self._verdict, f"from-{self.id}")


def test_evaluate_runs_injected_gates_in_priority_order(tmp_path: Path):
    engine = _engine_mod()
    log: list[str] = []

    # Supplied out of priority order → engine must sort ascending by priority.
    high = _RecordingGate("high", 30, "pass", log)
    low = _RecordingGate("low", 10, "pass", log)
    mid = _RecordingGate("mid", 20, "pass", log)

    verdict, msg = engine.evaluate(tmp_path, _gates=[high, low, mid])
    assert verdict == "pass"
    assert msg == ""
    assert log == ["low", "mid", "high"], log


def test_evaluate_short_circuits_on_first_blocking_injected_gate(tmp_path: Path):
    engine = _engine_mod()
    log: list[str] = []

    blocker = _RecordingGate("blocker", 10, "block", log)
    after = _RecordingGate("after", 20, "pass", log)

    verdict, msg = engine.evaluate(tmp_path, _gates=[after, blocker])
    assert verdict == "block"
    assert msg == "from-blocker"
    # The lower-priority blocker runs first and the higher-priority gate never does.
    assert log == ["blocker"], log


def test_evaluate_advise_verdict_does_not_block(tmp_path: Path):
    """A non-'block' verdict (e.g. 'advise') is treated as pass-through — the
    engine only short-circuits on the literal 'block' string."""
    engine = _engine_mod()
    log: list[str] = []

    advisor = _RecordingGate("advisor", 10, "advise", log)
    tail = _RecordingGate("tail", 20, "pass", log)

    verdict, msg = engine.evaluate(tmp_path, _gates=[advisor, tail])
    assert verdict == "pass"
    assert msg == ""
    assert log == ["advisor", "tail"], log


# ── smells.gate.run over real .py trees ──────────────────────────────────────
# Targets .agents/lib/gates/code/smells.py lines 33-139: _limit env parsing,
# _long_method, _long_params, _nested_conditional, _iter_py pruning, the run()
# dir/file/None/missing dispatch, syntax-error skip, and the advise/pass return.


def _ctx(engine, path: Path):
    return engine.GateContext(chunk_path=path)


def test_smells_pass_on_none_and_missing_path(tmp_path: Path):
    # run() guard clause: line 119-120 (None or not exists → pass).
    smells = _smells_mod()
    assert smells.run(None) == ("pass", "")
    assert smells.run(tmp_path / "does-not-exist") == ("pass", "")


def test_smells_pass_on_clean_tree(tmp_path: Path):
    smells = _smells_mod()
    (tmp_path / "clean.py").write_text("def f(x):\n    return x + 1\n")
    assert smells.run(tmp_path) == ("pass", "")


def test_smells_long_method_detected(tmp_path: Path):
    # _long_method: lines 42-53. Default limit 30 → a 32-line body advises.
    smells = _smells_mod()
    body = "\n".join(f"    a{i} = {i}" for i in range(32))
    (tmp_path / "long.py").write_text(f"def stretchy():\n{body}\n")
    verdict, msg = smells.run(tmp_path)
    assert verdict == "advise"
    assert "long-method" in msg
    assert "stretchy" in msg


def test_smells_long_method_async_detected(tmp_path: Path):
    # Same detector across the AsyncFunctionDef isinstance branch (line 45).
    smells = _smells_mod()
    body = "\n".join(f"    a{i} = {i}" for i in range(32))
    (tmp_path / "along.py").write_text(f"async def stretchy_async():\n{body}\n")
    verdict, msg = smells.run(tmp_path)
    assert verdict == "advise"
    assert "long-method" in msg
    assert "stretchy_async" in msg


def test_smells_long_params_detected(tmp_path: Path):
    # _long_params: lines 56-73. Default limit 5 → 6 positional params advises.
    smells = _smells_mod()
    (tmp_path / "wide.py").write_text("def broad(a, b, c, d, e, f):\n    return None\n")
    verdict, msg = smells.run(tmp_path)
    assert verdict == "advise"
    assert "long-params" in msg
    assert "broad" in msg


def test_smells_long_params_counts_vararg_kwarg_kwonly(tmp_path: Path):
    # Exercise the vararg / kwarg / kwonly arms of the param count (lines 61-67):
    # 2 posonly + 1 arg + 1 kwonly + *args + **kw = 6 > 5.
    smells = _smells_mod()
    (tmp_path / "starred.py").write_text("def variadic(p1, p2, /, a, *args, kw1, **kwargs):\n    return None\n")
    verdict, msg = smells.run(tmp_path)
    assert verdict == "advise"
    assert "long-params" in msg
    assert "variadic" in msg


def test_smells_nested_conditional_detected(tmp_path: Path):
    # _nested_conditional: lines 76-95. Descend increments depth per blocker
    # (If/For/While/Try/With). Default limit 4 → depth 4 advises.
    smells = _smells_mod()
    src = (
        "def deeply(x):\n"
        "    if x:\n"
        "        for y in range(x):\n"
        "            while y:\n"
        "                with open('f') as fh:\n"
        "                    return fh\n"
    )
    (tmp_path / "nested.py").write_text(src)
    verdict, msg = smells.run(tmp_path)
    assert verdict == "advise"
    assert "nested-conditional" in msg
    assert "deeply" in msg


def test_smells_reports_multiple_findings_across_files(tmp_path: Path):
    # findings accumulation across _iter_py + the join at lines 133-138.
    smells = _smells_mod()
    (tmp_path / "wide.py").write_text("def broad(a, b, c, d, e, f):\n    return None\n")
    body = "\n".join(f"    a{i} = {i}" for i in range(32))
    (tmp_path / "long.py").write_text(f"def stretchy():\n{body}\n")
    verdict, msg = smells.run(tmp_path)
    assert verdict == "advise"
    assert "long-params" in msg
    assert "long-method" in msg
    assert msg.count("\n") >= 1  # joined multi-line message


def test_smells_skips_syntax_error_files(tmp_path: Path):
    # run() try/except at lines 129-132 swallows SyntaxError and keeps going.
    smells = _smells_mod()
    (tmp_path / "broken.py").write_text("def oops(:::\n")
    (tmp_path / "fine.py").write_text("def f():\n    return 1\n")
    assert smells.run(tmp_path) == ("pass", "")


def test_smells_prunes_skip_dirs(tmp_path: Path):
    # _iter_py SKIP_DIRS pruning: lines 99-101. A smelly file under node_modules
    # must not surface.
    smells = _smells_mod()
    nm = tmp_path / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    body = "\n".join(f"    a{i} = {i}" for i in range(40))
    (nm / "huge.py").write_text(f"def buried():\n{body}\n")
    assert smells.run(tmp_path) == ("pass", "")


def test_smells_on_single_file_path_uses_parent_dir(tmp_path: Path):
    # run() root resolution when chunk_path is a file (line 122): root = parent.
    smells = _smells_mod()
    body = "\n".join(f"    a{i} = {i}" for i in range(32))
    target = tmp_path / "long.py"
    target.write_text(f"def stretchy():\n{body}\n")
    verdict, msg = smells.run(target)
    assert verdict == "advise"
    assert "long-method" in msg


def test_smells_env_tunables_tighten_and_default_on_bad_value(tmp_path: Path, monkeypatch):
    # _limit: lines 32-39. Valid int tightens the threshold; a non-int value
    # falls back to the default (ValueError arm), and an empty/unset var also
    # returns the default (falsy `raw` arm).
    smells = _smells_mod()

    # A 6-line method is clean under the default (30) but smelly under limit 3.
    (tmp_path / "smallish.py").write_text("def modest():\n" + "\n".join(f"    a{i} = {i}" for i in range(6)) + "\n")

    # Unset → default 30 → clean.
    monkeypatch.delenv("SMELL_LONG_METHOD_LINES", raising=False)
    assert smells.run(tmp_path) == ("pass", "")

    # Tightened → smelly.
    monkeypatch.setenv("SMELL_LONG_METHOD_LINES", "3")
    verdict, msg = smells.run(tmp_path)
    assert verdict == "advise"
    assert "long-method" in msg

    # Garbage value → ValueError arm → falls back to default 30 → clean again.
    monkeypatch.setenv("SMELL_LONG_METHOD_LINES", "not-an-int")
    assert smells.run(tmp_path) == ("pass", "")


def test_smells_gate_object_conforms_and_runs_via_context(tmp_path: Path):
    # _SmellsGate.run: lines 105-111 — pull chunk_path off the ctx and delegate.
    engine = _engine_mod()
    smells = _smells_mod()

    g = smells.gate
    assert g.id == "smells"
    assert g.priority == 20
    assert callable(g.run)

    body = "\n".join(f"    a{i} = {i}" for i in range(32))
    (tmp_path / "long.py").write_text(f"def stretchy():\n{body}\n")

    verdict, msg = g.run(_ctx(engine, tmp_path))
    assert verdict == "advise"
    assert "long-method" in msg


def test_smells_gate_run_pass_on_ctx_without_chunk_path(tmp_path: Path):
    # _SmellsGate.run getattr default None → run(None) → pass (line 110 default).
    smells = _smells_mod()

    class _Bare:
        pass

    assert smells.gate.run(_Bare()) == ("pass", "")
