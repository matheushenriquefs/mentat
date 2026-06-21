# Plugins — Mentat Plugin API

Plugins extend or replace Mentat's built-in harness adapter. ADR-0009 documents the design decisions.

---

## Plugin shape

```python
from dataclasses import dataclass
from typing import Protocol

class HarnessProvider(Protocol):
    name: str
    def invoke(self, cmd: list[str]) -> int: ...

@dataclass
class MentatPlugin:
    name: str
    harness: HarnessProvider | None = None
```

A plugin is a factory function returning `MentatPlugin`. Name must be unique.

---

## Available slots

| Slot | Kind | Description |
|---|---|---|
| `harness` | `first` | AI CLI adapter. Built-in: `claude-code`, `cursor`. |

Kind `first` — first plugin in ordered list whose slot is non-`None` wins.
The built-in acts as last-resort fallback if no plugin provides the slot.

**Diff rendering** is configured via `diff_tool` in `~/.mentat/config.toml`. Mentat
prints a suggestion at run end (`git diff` or the configured tool). Not a plugin slot.

---

## Writing a harness plugin

### 1. Implement the provider

```python
# mentat_plugin_aider/__init__.py
from mentat.plugins import MentatPlugin, HarnessProvider

class AiderHarness:
    name = "aider"

    def invoke(self, cmd: list[str]) -> int:
        import subprocess
        return subprocess.run(["aider", *cmd]).returncode

def plugin() -> MentatPlugin:
    return MentatPlugin(name="aider-harness", harness=AiderHarness())
```

### 2. Register the entry point

```toml
# pyproject.toml of your plugin package
[project.entry-points."mentat-plugin"]
aider = "mentat_plugin_aider:plugin"
```

### 3. Declare in config

```toml
# ~/.mentat/config.toml
harness = "aider-harness"
plugins = { order = ["aider-harness"] }
```

> **`HarnessProvider` is a documented-future-API (ADR-0009).** The real harness seam
> today is `implement/scripts/harness/{claude_code,cursor}.py`. `_invoke_harness` is not yet
> wired through the Protocol. Use `--harness` CLI flag or `harness =` in config.toml to
> select built-ins; third-party adapters registered here are deferred to F5 for live wiring.

---

## Discovery

At startup, mentat calls:

```python
from importlib.metadata import entry_points
plugins = [
    ep.load()()
    for ep in entry_points(group="mentat-plugin")
]
```

Each entry point must be a zero-argument factory returning `MentatPlugin`.

---

## Naming convention

PyPI package name: `mentat-plugin-<name>`.

---

## Future slots

Ordering primitives (`enforce: 'pre'|'post'`, `apply: 'install'|'orchestrate'`) are
not part of the current plugin API — see ADR-0009. New slots are added as optional
`MentatPlugin` fields; existing plugins continue to work without changes.
