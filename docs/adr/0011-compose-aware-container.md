# ADR 0011: Compose-aware container bring-up

Status: Accepted
Date: 2026-06-21

## Context

ADR-0004's mantra is "run project tools in the container, never the host." Bring-up
(`mentat-container`) assumes a repo's `docker-compose.yml` *wraps the app* — that exactly
one service builds or mounts the source tree, and that service is the workspace.

That assumption breaks on a **sidecar-only** compose. Some repos run compose only to spin
up 3rd-party services (a database, a cache, a private Nitter) while the app itself runs
outside compose. Walked against such a file (e.g. bebop's `nitter` + `nitter-redis`), the
old `_parse_compose_service` flagged any service with a cwd-mount as the workspace — so a
config-file bind (`./nitter.conf:/src/nitter.conf:ro`) made `nitter` (the `zedeus/nitter`
image) look like the workspace. mentat then ran the agent's toolchain inside Nitter, which
has no Python/node, and the devcontainer was silently broken. The real app has *no* service
— it runs on the host and reaches sidecars at `localhost:<port>`.

The gap: a config-file bind-mount is not source code, so a cwd-mount is too loose a signal
for "this is the workspace," and there was no path for "compose provides services, but the
workspace needs its own dev container layered onto that compose network."

## Decision

**Sidecar detection (C1).** A service is a workspace candidate only if it `build`s **or**
bind-mounts the *worktree root* (`.` / `./` / `..` / `$PWD`) — a mount of a single config
file does not count. Zero candidates → raise the typed `SidecarOnlyCompose` signal carrying
the parsed service names (distinct from the ambiguous-pick `ValueError`), so the caller can
branch instead of mis-picking.

**A — default: layer a generated dev service (C2).** On `SidecarOnlyCompose`, `synth_spec`
returns a devcontainer.json whose `dockerComposeFile` lists **both** the project compose and
a generated overlay (`["../docker-compose.yml", "mentat-dev.compose.yml"]`) with
`service: mentat-dev`. The overlay defines a dev service that uses the mentat toolchain
image, mounts the worktree at the workspace folder, and runs `sleep infinity`. Multi-file
compose merges the two into **one** compose project, so the dev service joins the project's
single `default` network automatically — no explicit `networks:` block. Sidecars resolve by
**service name** (`nitter:8080`), not `localhost`. The agent runs containerized; the
ADR-0004 mantra holds.

`synth_spec` stays pure (no filesystem writes): it hands the overlay back as text in
`SynthResult.extra_files`, and `container.py` writes it beside `devcontainer.json`. The same
return shape closes a latent gap where the `compose.yml.tmpl` branch rendered a compose file
the caller never wrote — it is now returned as `extra_files["docker-compose.yml"]`.

**B — opt-out: `runtime = "host"` (C3).** A repo that genuinely cannot containerize sets
`runtime = "host"` in config. Bring-up then skips the container and runs tools on the host,
after one loud per-worktree warning that ADR-0004 isolation is forfeited (host interpreter
may be unset; worktree not sandboxed). Only the literal value `"host"` opts out; missing,
malformed, or any other value fails safe to the containerized path. Opt-in only — never the
default.

## Consequences

- The ADR-0004 mantra is **preserved by A**: sidecar-only repos still run containerized via
  the layered dev service. **B is a documented, loud forfeit**, not a silent fallback.
- App code that reached a sidecar at `localhost:<port>` on the host must use the service
  name (`<service>:<port>`) inside the dev container. mentat documents this in the
  `mentat-container` SKILL; it does not rewrite the app's `localhost` references.
- Compose parsing stays the existing stdlib line-regex approach (ADR-0008); no PyYAML.
- The overlay is namespaced (`mentat-dev` / `mentat-dev.compose.yml`) and written only when
  no user `devcontainer.json` exists, so it never clobbers user files.
- Unchanged: the Dockerfile, standalone-compose, and existing-devcontainer detection paths.
  Only the sidecar-only branch is new.
