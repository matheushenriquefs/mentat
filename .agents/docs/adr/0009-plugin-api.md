# ADR 0009: Plugin API — Vite-derived, two slots, entry-point discovery

Status: Accepted (locked)
Date: 2026-06-10

## Context

Mentat has two integration points that third parties legitimately want to extend:
diff rendering (`git diff` replacement) and harness adapters (AI CLI selection).
Hard-coding these as Python conditionals would require forking mentat to add Aider,
Codex, or a custom diff tool. A plugin system isolates the extension points.

Vite's plugin API is the reference (vite.dev/guide/api-plugin): factory function
returning an object with a `name` plus optional slot implementations. Resolution
per slot is `first` — first plugin in ordered list whose slot is non-None wins.

## Decision

**Shape:** Python `dataclass(frozen=True)` with `name`, optional slot fields.

```python
@dataclass(frozen=True)
class MentatPlugin:
    name: str
    diff: DiffProvider | None = None
    harness: HarnessProvider | None = None
```

**Two slots (v1, locked):**
- `diff` — replaces `git diff` rendering. Built-in: `git` (always last-resort fallback).
- `harness` — AI CLI adapter. Built-in: `claude-code`, `cursor`.

**Resolution per slot:** `first` kind. Iterate plugins in config-declared order.
First plugin whose slot field is non-None wins. Built-ins run if no plugin claims.

**Plugin factory:** zero-argument callable returning `MentatPlugin`.

**Discovery:** `importlib.metadata.entry_points(group="mentat-plugin")`. Each
entry point name maps to a factory. Load order = config `plugins` list order;
plugins not in the list load last (advisory order only).

**User config** (`~/.mentat/config.jsonc`):
```jsonc
{
  "harness": "claude-code",
  "diff_tool": null,
  "plugins": ["delta-diff", "my-harness"]
}
```

`harness` and `diff_tool` are slot-selector aliases for the most common case.
`plugins` is the ordered list for entry-point discovery.

**`editor` key dropped.** Never shipped; drop from config schema.

**Naming convention:** PyPI `mentat-plugin-<name>`. Mirrors Vite's `vite-plugin-X`.

## Rejected alternatives

- **Explicit registry file** (JSONC with plugin paths): registry drift as plugins
  install/uninstall; entry points are the Python standard for this pattern.
- **Plugin class hierarchy** (`DiffPlugin(BasePlugin)`): mixin inheritance;
  dataclass + Protocol is flatter and matches Vite's shape more closely.
- **v1 ordering primitives** (`enforce: 'pre'|'post'`, `apply: 'install'|'orchestrate'`):
  not needed until a real use case emerges. Document as planned-extension; add
  optional fields when a plugin requires them.

## Consequences

`mentat.plugins` module exports `MentatPlugin`, `DiffProvider`, `HarnessProvider`.
Plugin registry in `mentat.plugins.registry` handles entry-point discovery,
config-ordered loading, and first-wins slot resolution. Built-ins in
`mentat.plugins.builtin.{git_diff,claude_code,cursor}`.

`pip install mentat-plugin-delta` makes the delta diff provider available.
No mentat config change needed beyond adding `"delta-diff"` to `plugins[]`.

Future slots: add optional field to `MentatPlugin`; existing plugins unaffected.
