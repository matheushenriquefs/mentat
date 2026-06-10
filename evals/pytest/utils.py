import os

AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".agents", "agents"))
GATES_LLM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".agents", "lib", "gates", "llm"))
FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "promptfoo", "fixtures"))

_GATE_NAME_MAP: dict[str, str] = {
    "mentat-plan-reviewer": "plan",
    "mentat-test-reviewer": "test",
    "mentat-bug-reviewer": "bug",
    "mentat-smell-reviewer": "smell",
}


def read_fixture(name: str, filename: str) -> str:
    path = os.path.join(FIXTURES_DIR, name, filename)
    with open(path) as f:
        return f.read()


def read_agent(name: str) -> str:
    short = _GATE_NAME_MAP.get(name)
    if short:
        gate_path = os.path.join(GATES_LLM_DIR, f"{short}.md")
        if os.path.exists(gate_path):
            with open(gate_path) as f:
                return f.read()
    path = os.path.join(AGENTS_DIR, f"{name}.md")
    with open(path) as f:
        return f.read()
