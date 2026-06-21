# ADR 0009: Plugin API — Vite-derived, one slot (harness), entry-point discovery

Status: Accepted (locked)
Date: 2026-06-10
Amended: 2026-06-20 (v2 — harness-only slot set; HarnessProvider as documented-future-API)

## Context

Mentat has one third-party extension point: harness adapters (AI CLI selection). A plugin
system isolates the extension point so adding Aider, Codex, or a custom CLI does not require
forking mentat. Diff rendering is not a plugin concern — users configure `diff_tool` as a
plain config key.

Vite's plugin API is the reference (vite.dev/guide/api-plugin): factory function returning
an object with a `name` plus optional slot implementations. Resolution per slot is `first`
— first plugin in ordered list whose slot is non-None wins.

## Decision

**Shape:** Python `dataclass` with `name`, optional `harness` slot.

```python
@dataclass
class MentatPlugin:
    name: str
    harness: HarnessProvider | None = None
```

**One slot:**
- `harness` — AI CLI adapter. Built-in: `claude-code`, `cursor`.

Diff rendering is configured via `diff_tool` in `~/.mentat/config.toml`. Mentat prints a
suggestion at run end (`git diff` or the configured tool). `diff_tool` is a plain config
key, not a plugin slot.

**HarnessProvider is documented-future-API.** The real harness seam today is
`implement/scripts/harness/{claude_code,cursor}.py` — two live adapters invoked directly by
`implement.py`. `HarnessProvider` Protocol stays in the module as the intended extension
contract; `_invoke_harness` routing through it is deferred to F5. Third-party adapters may
implement the Protocol today but are not yet auto-invoked by `_invoke_harness`.

**Resolution per slot:** `first` kind. Iterate plugins in config-declared order.
First plugin whose slot field is non-None wins. Built-ins run if no plugin claims.

**Plugin factory:** zero-argument callable returning `MentatPlugin`.

**Discovery:** `importlib.metadata.entry_points(group="mentat-plugin")`. Each
entry point name maps to a factory. Load order = config `plugins` list order;
plugins not in the list load last (advisory order only).

**User config** (`~/.mentat/config.toml`):
```toml
harness = "claude-code"
diff_tool = "delta"          # plain suggestion printed at run end — not a plugin slot
plugins = { order = ["my-harness"] }
```

`harness` selects the built-in or registered harness adapter.
`plugins.order` is the ordered list for entry-point discovery.

**`editor` key dropped.** Never shipped; absent from config schema.

**Naming convention:** PyPI `mentat-plugin-<name>`. Mirrors Vite's `vite-plugin-X`.

## Rejected alternatives

- **Explicit registry file** (JSONC with plugin paths): registry drift as plugins
  install/uninstall; entry points are the Python standard for this pattern.
- **Plugin class hierarchy** (`DiffPlugin(BasePlugin)`): mixin inheritance;
  dataclass + Protocol is flatter and matches Vite's shape more closely.
- **Diff as a plugin slot:** users want a suggestion at run end, not an API surface
  for programmatic diff rendering; `diff_tool` config key is sufficient.
- **v1 ordering primitives** (`enforce: 'pre'|'post'`, `apply: 'install'|'orchestrate'`):
  not needed until a real use case emerges. Document as planned-extension; add
  optional fields when a plugin requires them.

## Consequences

`mentat.plugins` module exports `MentatPlugin`, `HarnessProvider`. Plugin registry in
`mentat.plugins.registry` handles entry-point discovery, config-ordered loading, and
first-wins harness slot resolution. Built-ins in `mentat.plugins.builtin.{claude_code,cursor}`.

Future slots: add optional field to `MentatPlugin`; existing plugins unaffected.
