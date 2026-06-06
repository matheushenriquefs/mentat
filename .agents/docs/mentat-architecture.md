# dmux architecture

The *why* of each decision. Cheatsheet tells you what to do; this
tells you why we do it that way.

## Holding branch instead of dmux's Merge

(Decision of record: ADR 0002 — rejected alternatives and evidence there.)

dmux's Merge action (inside the `m` pane menu) runs `git commit` and
`git merge` *on the host*. Team repos with container-side pre-commit
(e.g. `pre-commit` installed via uv inside the container, container-only
formatters) fail those commits — the hook script written to
`.git/hooks/pre-commit` lives on the host (because `.git/` is
bind-mounted out of the container), and fires from the host shell where
its tools aren't installed.

The fix: route every `git commit` through the container via
`mentat-container-run`, and don't use dmux's Merge. Instead, the planner
pane holds `branch/<feature>` with no commits of its own, each dmux
worktree branches from `main`, and the implementer agent runs
`/to-rebase` at the end of its session to fast-forward the holding
branch onto its tip. Because the holding branch has no commits beyond
its merge-base with `dmux-{ts}`, the rebase is fast-forward — no
`git commit` is invoked, no pre-commit fires on host.

Push the holding branch and open a PR when all worktrees have landed.
dmux's pane menu (`m` → Create GitHub PR) still works from the planner
pane, but `gh pr create` from a host shell does the same.

## Commits inside the container, per slice

Two principles compose:

1. **Pre-commit lives inside the container.** Installed there by the
   devcontainer build. Host doesn't have the tools.
2. **TDD vertical slices are natural commit boundaries.** One failing
   test → minimal impl → green is one logical change.

So `/to-commit`:

- Stages the changes.
- Invokes `/caveman-commit` for the message.
- Runs the actual `git commit` via `mentat-container-run`.

Slice scoping is implicit from *when* `/to-commit` runs — after each
green slice, when the only dirty files are that slice's. No need for
the command itself to enforce scope.

## Hooks global, plans/skills shared, context per-repo

| Thing | Scope | Why |
| --- | --- | --- |
| `~/.dmux/hooks/` | Global | Workflow is the same across repos. |
| `~/.agents/plans/` | Global | One folder to grep across all features. |
| `~/.agents/commands/` | Global | Tool-agnostic prompts. |
| `~/.agents/bin/` | Global | Helpers infer slug from `$PWD`. |
| `~/.agents/AGENTS.md` | Global | Cross-agent rules; CLAUDE.md imports it. |
| `~/.agents/skills/` | Global | One skills dir, every agent symlinks to it. |
| `<repo>/context/` | Per-repo | Codebase maps, prompts specific to this repo. |
| `<repo>/.env` | Per-repo | Secrets vary across repos. |

The split: things that describe **the work** (plans, commands, hooks) are
global. Things that describe **the codebase** (context, .env) are per-repo.
Per-repo `<repo>/.dmux-hooks/` overrides global when needed
(first-match-wins).

## Sub-agent delegation, set globally not per-command

Commands fan out — `/to-plan` grills, `/to-implement` runs TDD slices, review
steps check diffs. The choice per delegation is output shape: spawn cavecrew
for a compressed finding (~60% fewer tokens, injects into main context small),
spawn vanilla (`Explore`, `Code Reviewer`) for prose. The rule lives in
`~/.agents/AGENTS.md`, not in command bodies — commands stay lean and say
nothing about which agent to spawn. Claude Code reads it via the
`@~/.agents/AGENTS.md` import in CLAUDE.md; Codex and Cursor read AGENTS.md
directly, so the same rule holds whichever tool drives the worktree.

`skill-creator` (in `/to-scaffold`) stays vanilla — specialized drafting, not
a generic builder.

## `/mentat-researcher` is a context firewall

The 90% delegation case is ground-truthing: check a fact against
docs/papers/repos, return a synthesized answer, so the planner/implementer
window never fills with raw search results and dead ends.

Runs on the cheapest capable model the harness offers — ground-truthing is
recall plus source-tracing, not planner judgment, so spending the strong
model's context on it is the waste the firewall prevents. Returns an answer,
not a transcript: ≤3 sentences plus source lines.

Procedure, not persona: the task is recall-dependent, and role prefixes hurt
recall (see ADR 0001 for the source evidence). So it's operating loop, output
contract, and a hard primary-source-over-blogs gate, no persona preamble.

External-knowledge sibling of `cavecrew-investigator` — investigator greps
*inside* the repo, `/mentat-researcher` traces facts *outside* it.

## Devcontainer CLI overrides instead of editing devcontainer.json

Team repos ship a `.devcontainer/devcontainer.json` we can't modify.
Worktrees need git resolution the committed config doesn't provide —
the worktree's `.git` is a pointer file referencing
`<parent-repo>/.git/worktrees/<slug>`, which isn't visible from a
workspace-only mount.

`devcontainer up` accepts `--mount` and `--remote-env` flags that
layer over the committed config *per invocation*. `mentat-container-up`
injects:

- `--mount type=bind,source=$ROOT/.git,target=$ROOT/.git` — so the
  worktree's `.git` pointer resolves inside the container.
- `--remote-env GIT_DIR=$ROOT/.git/worktrees/$SLUG`
- `--remote-env GIT_WORK_TREE=/workspaces/$SLUG`

Two gotchas verified empirically:

- `readonly=true` on `--mount` is rejected — only `type`, `source`,
  `target`, `external` parse. Bind being read-write into the container
  is harmless; git ops route through `GIT_DIR` to worktree-local refs.
- The host's uid owning `.git` triggers `fatal: detected dubious
  ownership` for the container's `vscode` user. `mentat-container-up` runs
  `git config --global --add safe.directory` post-up to fix.

## Why `/to-commit` is a slash command, not a helper script

`/caveman-commit` is message-only. The ritual is three steps: stage →
invoke skill → commit. Bundling them in `/to-commit` gives the ritual
a name and prevents drift. The agent invokes the skill in-process —
no subprocess needed, so no bash wrapper either.

Compare `devcontainer-{up,down,run}`: those are bash helpers because
they have two consumers (the agent calls them, and the dmux hooks
call them from bash). A slash command wouldn't work for the hook side.

## What we gave up

Enumerated in ADR 0002: dmux's Merge action, the `pre_merge` hook, automatic
worktree cleanup on merge, and dmux's AI-generated commit messages. `x` still
tears down via `before_worktree_remove`; close manually after `/to-rebase`.

## Why `/to-rebase` runs from the implementer pane

The original flow had the user context-switch to the planner pane and
run `git rebase dmux-{ts}` by hand. `/to-rebase` lifts that step into
the agent's session. Two mechanics make this safe:

- `git -C $ROOT rebase` runs the rebase *as if* in the planner's
  working tree, using the shared `.git/`. The agent never checks out
  the holding branch in its own worktree (which would conflict with the
  planner's checkout).
- `git merge-base --is-ancestor $HOLDING HEAD` is the safety check. If
  the holding branch has commits not in the dmux tip, the rebase would
  replay them — firing host-side pre-commit. `/to-rebase` aborts in
  that case and tells the user, rather than corrupting the branch.

The planner pane only re-engages at the end of the feature, for
`git push` and `gh pr create`.
