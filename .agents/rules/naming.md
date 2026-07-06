---
paths:
  - ".agents/skills/*/scripts/*.py"
  - ".agents/lib/**/*.py"
  - "tests/**/*.py"
  - ".agents/skills/*/SKILL.md"
---

# Naming

One name per concept, everywhere it appears — code, CLI, docs, event log. A
reader who learns a name in one surface should find it unchanged in every
other surface.

## Entities and data access

- A value object is a frozen `@dataclass`, named for the thing it is:
  `Agent`, `Chunk`, `Slice`, `Event`. Never suffix `Record` or `Info`
  (`AgentRecord` is `Agent`).
- Data access for an entity is `<Entity>DAO` (`AgentDAO`, `ChunkDAO`),
  co-located with the entity it serves.
- A held resource — a connection, a lock, a running process — is
  `<Thing>Service`, not a bare noun or a `Manager`.
- A raised exception is `<X>Error` (`GateError`, `ConfigError`), never
  `<X>Exception`.

## Enums, statuses, and reasons

- A closed set of wire values is a `Literal[str]` type alias, not an `Enum`
  class and not a bare `str`: `AgentStatus = Literal["pending", "running",
  "stopped", "reaped"]`.
- Every status field pairs with one unified `status_reason: StatusReason`
  column/attribute — there is one `StatusReason` type across the schema, not
  a `StatusReason` per entity.
- A reason value is a specific cause label, Stripe-decline-code style
  (`gate_failed`, `rebase_conflicted`, `worker_died`) — never a generic verb
  like `failed` or `error`. This is the opposite of the event-name rule
  below: event *names* are generic-verb-first, reason *values* are specific.

## Verb dictionary (Python)

- `make_*` mints or builds a new value or entity in memory — it never
  persists (`make_agent_id` mints a uuid7, `make_slice_id` mints a slice
  key). If the function writes to a store, it is `create_*`/`insert_*`, not
  `make_*`.
- A pure derivation from parts already in hand takes no verb at all —
  `chunk_slug(chunk_id, slug)`, in the spirit of `posixpath.join`. Reach for
  a bare noun function before reaching for `make_*`/`get_*` on a
  computation that owns no state.
- `create_*` / `insert_*` / `append_*` / `save_*` persist. Pick the one that
  names the actual operation — `append_*` for an append-only log
  (`EventDAO.append`), `insert_*`/`create_*` for a row that can be the only
  one, `save_*` only for an upsert.
- `*_or_fail` is the throwing twin of a lookup that returns `None` on a
  miss — `get_by_id` returns `Entity | None`, `get_by_id_or_fail` raises.
  Do not silently swallow the miss inside `get_by_id` itself.
- `*_or_new` builds an in-memory default when absent; `*_or_create` also
  persists that default. Never use one name to mean the other.
- Reads are `get_by_id` (singular, by key) and `list_by_*` (collection, by
  a non-unique attribute) — `EventDAO.list_by_agent`, `SliceDAO.get_by_id`.
- Banned verbs: `fetch_*`, `find_*`. They collide with `get_by_id`/
  `list_by_*` and add no distinct meaning — pick the pair above instead.

## CLI subcommand verbs

Skills follow Laravel Artisan semantics: the skill is the "group," the
subcommand is the action. This governs vocabulary, not literal `:`
syntax — `mentat-log emit`, not `mentat-log:emit`.

- Read a collection: `list`. Read one thing's overview: `show`. Read live
  process state: `status`. Never `query` as a subcommand verb.
- Mint something new: `make` or `create` (mirrors the Python verb split
  above).
- Destroy or reset: `prune` (age-based delete), `reset` (return to a known
  state), `fresh` (rebuild from nothing) — pick the one that names the
  actual effect, never a bare `clear` or `delete`.
- Argument notation in docs and help text: `{arg}` required, `{arg?}`
  optional, `{--flag}` a flag.
- A command stays **bare** — no subcommand — when it is a subsystem's
  single primary action with no siblings (`mentat-container run`'s sibling
  `up`/`down` exist, but a subsystem with exactly one verb, e.g. `track`,
  takes no subcommand at all).
- Deliberate exceptions honor a stronger tool idiom over the Laravel one
  when the borrowed tool's model is a closer match: `diff` mimics git
  (the holding-branch model here is git's), `doctor` mimics the
  cross-tool diagnostic idiom (`brew doctor`). Do not invent a third
  exception without the same justification — name the tool whose idiom is
  stronger and why.

## Module naming

- Scope a file by the concept it holds, do not prefix it with its skill or
  package name: `harness/utils.py`, not `harness_utils.py`. The directory
  already gives the scope; repeating it in the filename is noise.
- See `architecture.md` for the broader group-by-function rule this serves.

## Migrations

- A forward-only migration function is `create_<table>` — one function per
  table, applied once via `PRAGMA user_version` (see `database.md`). Never
  `migrate_<n>` or `upgrade_<n>`; the table name is the durable identity,
  the migration ledger tracks which have run.

## Output artifact

- The file a skill or agent produces as its handoff result is an
  **artifact** (`summary.md` is the per-agent status-bearing artifact) —
  not a "result," "deliverable," or "output file." One noun, used the same
  way in every `SKILL.md` and agent prompt.

## Locked taxonomy

These are cross-cutting decisions already applied across the schema, event
log, and plan frontmatter. A new field or symbol follows them; do not
reintroduce the retired alternative.

- **`kind`, never `class`.** `class` is a Python keyword (unusable as a
  dataclass field) and was overloaded between "plan classification" and
  "Python class." One taxonomy field name: `event.kind` (SQLite column),
  slice kind field, plan frontmatter `kind`.
- **Event names are flat snake_case, generic-verb-first (Stripe style).**
  `_started` is shared across entities; distinct outcomes get distinct
  verbs (`landed` vs `ejected`, `resolved` vs `canceled`), and a
  domain-only verb is fine where no generic one fits (`reaped`,
  `teardown`). No dot-separated resource namespace at the emit boundary
- Dotted emit names (resource dot verb) are wrong; flat `chunk_started` is right.
- **Self-referencing foreign keys are `<role>_id`.** `supervisor_id`,
  `resumed_from_id` on Agent — the role the referenced row plays, not a bare
  `parent_id`.
- **Timestamps end in `_at`.** `started_at`, `ended_at`, `expires_at` — UTC
  ISO-8601, always the suffix, never `_time`/`_ts`/a bare noun.
- **Isolation lexicon.** A **worktree** is the per-execution isolated
  filesystem env. Identity is **chunk-keyed**: `chunk_slug(chunk_id, slug)`
  names a chunk's branch, directory, and container label. The **chunk** is
  the durable identity for one slice attempt; the **agent** is the
  ephemeral worker process attached to it — an agent can die and respawn
  onto the same chunk. See `docs/adr/0005-ubiquitous-lexicon.md` and
  `docs/adr/0017-per-run-isolation.md` for the full lexicon.
