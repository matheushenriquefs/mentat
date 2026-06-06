import os

AGENTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "agents")
)
FIXTURES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "promptfoo", "fixtures")
)


def read_fixture(name: str, filename: str) -> str:
    path = os.path.join(FIXTURES_DIR, name, filename)
    with open(path) as f:
        return f.read()


def read_agent(name: str) -> str:
    path = os.path.join(AGENTS_DIR, f"{name}.md")
    with open(path) as f:
        return f.read()
