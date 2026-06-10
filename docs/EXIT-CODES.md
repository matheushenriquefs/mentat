# Exit Codes — Mentat

Mentat adopts [BSD `sysexits.h`](https://man7.org/linux/man-pages/man3/sysexits.h.3head.html)
as its exit-code convention. Honest framing: sysexits is the closest-to-standard convention
available, though it is not strictly followed by all GNU/Linux tooling. Mentat adopts it
deliberately for CI-script granularity — the same posture as requiring Docker (ADR-0004):
pick a convention, document it, move on.

---

## Authority table

| Code | sysexits constant | Mentat use |
|---|---|---|
| `0` | `EX_OK` | All slices landed, plan complete |
| `1` | — | Gate fail / TDD fail / generic mentat-domain failure |
| `42` | — | HITL sentinel — AFK ambiguity detected (documented exception; outside sysexits range) |
| `64` | `EX_USAGE` | CLI arg parse error / missing required flag / multi-slug input |
| `65` | `EX_DATAERR` | Malformed plan frontmatter / bad `config.jsonc` / bad JSONL |
| `66` | `EX_NOINPUT` | Input file missing (plan slug not found) |
| `69` | `EX_UNAVAILABLE` | Container down, harness unreachable |
| `70` | `EX_SOFTWARE` | Internal bug / unhandled Python exception |
| `73` | `EX_CANTCREAT` | Cannot create output (worktree mkdir fail, log dir read-only) |
| `75` | `EX_TEMPFAIL` | Transient — retry candidate (rate limit, transient network error) |
| `76` | `EX_PROTOCOL` | Upstream API broke contract (model returns malformed response) |
| `77` | `EX_NOPERM` | Permission denied (read-only test mount blocked write per ADR-0006) |
| `78` | `EX_CONFIG` | `~/.mentat/config.jsonc` missing or invalid |
| `128+N` | — | Signal-killed: `143` SIGTERM, `137` SIGKILL (POSIX) |

---

## Notes

**Code 1 vs 70:** Gate fail is a legitimate negative result, not a software bug.
`EX_SOFTWARE (70)` is reserved for unhandled Python exceptions only.

**Code 42:** Fabricated sentinel, not in sysexits. AFK plans exit 42 when
`AskUserQuestion` ambiguity is detected mid-session. Distinct from 0/1/signal codes.

**Code 99 dropped:** `mentat-container run` previously returned 99 when the
container was down. Replaced by 69 (`EX_UNAVAILABLE`).

**`≥2 = tool error` bucket retired:** Old catch-all replaced by sysexits-grounded
specifics above. Any exit code not in this table is a bug.

---

## Adoption status

All exit codes emitted by `.agents/lib/` and `bin/` map to an entry in this table.
`EX_UNAVAILABLE (69)` propagated across all scripts. Constants module: `.agents/lib/exits.py`.
