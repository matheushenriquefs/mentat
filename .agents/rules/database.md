# SQLite conventions (`mentat.db`)

Canonical runtime state lives in `~/.mentat/mentat.db` (override: `MENTAT_DB`).
Stdlib `sqlite3` only — typed DAOs in `lib/store.py`, no NL/text-to-SQL, no FTS5/vector.

## Connection

`store.connect()` applies, in order:

1. `PRAGMA busy_timeout=5000`
2. `PRAGMA journal_mode=WAL`
3. `PRAGMA foreign_keys=ON`
4. `PRAGMA synchronous=NORMAL`
5. `PRAGMA temp_store=MEMORY`

Writes use `BEGIN IMMEDIATE` with bounded retry on `SQLITE_BUSY`/`LOCKED`. A failed
canonical write of a terminal event raises — never swallowed.

Forward-only migrations via `PRAGMA user_version` and `_MIGRATIONS`.

## DDL (locked)

Harness transcript (not in sqlite):

```
FILE  ~/.mentat/logs/<repo>/<agent_id>/transcript.jsonl
```

```sql
CREATE TABLE slice (
  id         TEXT PRIMARY KEY,
  plan_slug  TEXT NOT NULL,
  key        TEXT NOT NULL,
  kind       TEXT NOT NULL,
  UNIQUE(plan_slug, key)
);

CREATE TABLE agent (
  id              TEXT PRIMARY KEY,
  supervisor_id   TEXT REFERENCES agent(id),
  resumed_from_id TEXT REFERENCES agent(id),
  forked_from_id  TEXT REFERENCES agent(id),
  harness         TEXT NOT NULL,
  pid             INTEGER,
  status          TEXT NOT NULL,
  status_reason   TEXT,
  started_at      TEXT NOT NULL,
  ended_at        TEXT
);

CREATE TABLE chunk (
  id            TEXT PRIMARY KEY,
  slice_id      TEXT NOT NULL REFERENCES slice(id),
  agent_id      TEXT NOT NULL REFERENCES agent(id),
  attempt       INTEGER NOT NULL DEFAULT 1,
  container_id  TEXT,
  worktree_path TEXT,
  status        TEXT NOT NULL,
  status_reason TEXT,
  started_at    TEXT NOT NULL,
  ended_at      TEXT
);

CREATE TABLE event (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       TEXT NOT NULL,
  kind     TEXT NOT NULL,
  payload  TEXT NOT NULL DEFAULT '{}',
  agent_id TEXT REFERENCES agent(id),
  chunk_id TEXT REFERENCES chunk(id)
);
CREATE INDEX event_by_agent ON event(agent_id, id);
CREATE INDEX event_by_chunk ON event(chunk_id, id);
```

## Naming

Per `.agents/rules/naming.md`:

- Value objects: frozen `@dataclass` (`Slice`, `Agent`, `Chunk`, `Event`)
- Data access: `<Entity>DAO` with `append`, `get_by_id`, `list_by_*`
- Event wire keys: flat snake_case (`chunk_started`); stored verbatim in `event.kind`
- Status/kind/reason: `Literal[str]` types (`AgentStatus`, `StatusReason`, …)
- Timestamps: ISO-8601 UTC with `_at` suffix on entity columns

## Determinism boundary

All reads and writes go through typed DAOs. No ad-hoc SQL outside `lib/store.py`.
