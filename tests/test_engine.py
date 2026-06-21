"""Slice deepen-gate-engine: lib/gates/engine.py Gate Protocol + evaluate()."""

from __future__ import annotations

from pathlib import Path


def _engine_mod():
    from lib.gates import engine

    return engine


def test_engine_discovers_gates_in_priority_order(tmp_path: Path):
    engine = _engine_mod()
    invoked: list[str] = []

    class _GateA:
        id = "stub_a"
        priority = 10

        def run(self, ctx: engine.GateContext) -> tuple[str, str]:  # type: ignore[name-defined]
            invoked.append("a")
            return ("pass", "")

    class _GateB:
        id = "stub_b"
        priority = 20

        def run(self, ctx: engine.GateContext) -> tuple[str, str]:  # type: ignore[name-defined]
            invoked.append("b")
            return ("pass", "")

    engine.evaluate(tmp_path, _gates=[_GateA(), _GateB()])
    assert invoked == ["a", "b"], f"gates not invoked in priority order: {invoked}"


def test_engine_short_circuits_on_first_block(tmp_path: Path):
    engine = _engine_mod()
    invoked: list[str] = []

    class _GateBlock:
        id = "block_gate"
        priority = 10

        def run(self, ctx: engine.GateContext) -> tuple[str, str]:  # type: ignore[name-defined]
            invoked.append("block")
            return ("block", "nope")

    class _GateAfter:
        id = "after_gate"
        priority = 20

        def run(self, ctx: engine.GateContext) -> tuple[str, str]:  # type: ignore[name-defined]
            invoked.append("after")
            return ("pass", "")

    verdict, msg = engine.evaluate(tmp_path, _gates=[_GateBlock(), _GateAfter()])
    assert verdict == "block"
    assert msg == "nope"
    assert "after" not in invoked, "second gate must not run after block"


def test_engine_returns_pass_when_no_gates_block(tmp_path: Path):
    engine = _engine_mod()

    class _PassGate:
        id = "pass_gate"
        priority = 10

        def run(self, ctx: engine.GateContext) -> tuple[str, str]:  # type: ignore[name-defined]
            return ("pass", "")

    verdict, msg = engine.evaluate(tmp_path, _gates=[_PassGate()])
    assert verdict == "pass"
    assert msg == ""


def test_precommit_gate_conforms_to_protocol():
    from lib.gates.code import precommit

    g = precommit.gate
    assert hasattr(g, "id"), "gate must have id"
    assert hasattr(g, "priority"), "gate must have priority"
    assert callable(getattr(g, "run", None)), "gate must have run method"


def test_engine_shared_walk():
    """precommit and smells must import _iter_files from _walk."""
    precommit_src = (Path(__file__).resolve().parents[1] / ".agents/lib/gates/code/precommit.py").read_text()
    smells_src = (Path(__file__).resolve().parents[1] / ".agents/lib/gates/code/smells.py").read_text()
    assert "_walk" in precommit_src or "from lib.gates._walk" in precommit_src, (
        "precommit.py must import from lib.gates._walk"
    )
    assert "_walk" in smells_src or "from lib.gates._walk" in smells_src, "smells.py must import from lib.gates._walk"
