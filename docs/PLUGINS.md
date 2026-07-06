# Plugins — harness extensibility

Mentat has one third-party extension point: harness adapters (AI CLI selection). It is a
filesystem convention, not a plugin registry — no entry points, no `MentatPlugin` dataclass,
no discovery step. `implement.py` maps a harness name straight to a script path and loads it.

---

## Built-in harnesses

```python
_HARNESS_DIR = Path(__file__).resolve().parent / "harness"
_HARNESS: dict[str, Path] = {
    "claude-code": _HARNESS_DIR / "claude_code.py",
    "cursor": _HARNESS_DIR / "cursor.py",
}
```

Built-in: `claude-code`, `cursor`, living at
`.agents/skills/mentat-implement/scripts/harness/{claude_code,cursor}.py`.

---

## Adding a harness adapter

### 1. Write the adapter module

```python
# .agents/skills/mentat-implement/scripts/harness/aider.py
def invoke(prompt: str, *, afk: bool, model: str | None = None, seed_summary: str | None = None):
    import subprocess
    return subprocess.run(["aider", "--message", prompt]).returncode
```

The module must expose `invoke(prompt, *, afk, model=None, seed_summary=None)` — the same
signature `_invoke_harness` calls on the built-ins.

### 2. Register it

Add an entry to the `_HARNESS` dict in `implement.py`:

```python
_HARNESS: dict[str, Path] = {
    "claude-code": _HARNESS_DIR / "claude_code.py",
    "cursor": _HARNESS_DIR / "cursor.py",
    "aider": _HARNESS_DIR / "aider.py",
}
```

### 3. Select it

```toml
# ~/.mentat/config.toml
harness = "aider"
```

Or per-run: `--harness aider` on the `mentat-implement` CLI.

---

## Other filesystem-convention seams

Two more surfaces extend the same way — drop a file, no registration step:

- **Reviewers** — drop a reviewer subagent body into `.agents/agents/<name>-reviewer.md`.
- **Code gates** — drop a Python module exposing `run(chunk_path) -> (verdict, message)` into `.agents/lib/gates/code/`.

**Diff rendering** is configured via `diff_tool` in `~/.mentat/config.toml`. Mentat
prints a suggestion at run end (`git diff` or the configured tool) — not a harness concern.
