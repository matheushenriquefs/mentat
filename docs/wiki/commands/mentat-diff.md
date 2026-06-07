# mentat-diff

> Stub — Plan D fills narrative.

Emits cumulative diff of a holding branch vs `main` (or a custom base SHA).

## Usage

```
mentat-diff [--stat-only] [--name-only] [--since=<sha>] [<holding-branch>]
```

## Flags

| Flag | Effect |
|------|--------|
| `--stat-only` | Print diffstat only |
| `--name-only` | Print changed file names only |
| `--since=<sha>` | Use `<sha>` as base instead of `merge-base main` |

## Auto-invocation

`mentat-orchestrate` calls `mentat-diff` automatically when all chunks land (zero ejects).
On any eject, it prints the manual-run command instead.
