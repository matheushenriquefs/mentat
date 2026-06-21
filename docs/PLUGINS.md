# Plugins — Mentat Plugin API

Plugins extend or replace Mentat's built-in slots: diff rendering, harness adapter,
reviewer subagents, and deterministic code gates. ADR-0009 documents the design decisions.

---

## Plugin shape

```python
# .agents/lib/plugins/types.py
from dataclasses import dataclass
from typing import Protocol

class DiffProvider(Protocol):
    def render(self, base: str, head: str) -> str: ...

class HarnessProvider(Protocol):
    def spawn(self, prompt: str, **opts) -> "HarnessResult": ...

@dataclass(frozen=True)
class MentatPlugin:
    name: str
    diff: DiffProvider | None = None
    harness: HarnessProvider | None = None
    # future slots: append optional fields here
```

A plugin is a factory function returning `MentatPlugin`. Name must be unique.

---

## Available slots

| Slot | Kind | Description |
|---|---|---|
| `diff` | `first` | Override `git diff` rendering. Built-in: `git`. |
| `harness` | `first` | AI CLI adapter. Built-in: `claude-code`, `cursor`. |

Kind `first` — first plugin in ordered list whose slot is non-`None` wins.
Built-ins act as last-resort fallback if no plugin provides the slot.

---

## Writing a plugin

### 1. Implement the provider

```python
# mentat_plugin_delta/__init__.py
from mentat.plugins import MentatPlugin

class DeltaDiff:
    def render(self, base: str, head: str) -> str:
        import subprocess
        result = subprocess.run(
            ["delta"],
            input=f"--- a\n+++ b\n{base}\n{head}",
            capture_output=True,
            text=True,
        )
        return result.stdout

def plugin() -> MentatPlugin:
    return MentatPlugin(name="delta-diff", diff=DeltaDiff())
```

### 2. Register the entry point

```toml
# pyproject.toml of your plugin package
[project.entry-points."mentat-plugin"]
delta = "mentat_plugin_delta:plugin"
```

### 3. Declare in config

```toml
# ~/.mentat/config.toml
plugins = ["delta-diff"]   # ordered; first provider of each slot wins
diff_tool = "delta"        # omit = built-in git
```

> **Note — layered config and plugin lists:** When a `<repo>/.mentat/config.toml`
> overlay is present, its `plugins` list **replaces** (not extends) the global list.
> Shallow merge means the entire `plugins` key from the repo wins. This avoids
> globally-installed plugins activating silently in scoped repos. If you need both
> global and repo plugins, list them all in the repo overlay.

---

## Harness plugin example

```python
# mentat_plugin_aider/__init__.py
from mentat.plugins import MentatPlugin, HarnessProvider

class AiderHarness:
    def spawn(self, prompt: str, **opts) -> object:
        import subprocess
        return subprocess.run(["aider", "--message", prompt], **opts)

def plugin() -> MentatPlugin:
    return MentatPlugin(name="aider-harness", harness=AiderHarness())
```

Declare in config:
```jsonc
{"harness": "aider-harness", "plugins": ["aider-harness"]}
```

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
