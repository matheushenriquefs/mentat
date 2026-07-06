# Resume a wedged chunk (HITL handoff)

Task-oriented. Goal: pick up a chunk that an unattended (`AFK`) agent could not
finish because it hit a decision only a human can make.

## What a wedge is

An AFK agent has no human to ask, so it cannot stall on a question. When it hits a
decision the plan does not resolve and cannot resolve safely on its own, it does not
guess. Instead it:

1. Writes the blocker — the question and the options it sees — to `summary.md` in
   the agent's log directory, with frontmatter `status: blocked`.
2. Ejects with a hitl-required reason and exits, **preserving its worktree** so the
   in-progress work is not lost.

A wedge is therefore distinct from a failure: nothing is broken, a human is needed.

## 1. Spot the wedge

A wedged chunk surfaces in the registry and prints a hitl-required ejection. Confirm
it and read the blocker:

```
/mentat-track list
/mentat-track report <agent-id>
```

`report` renders the `summary.md` the agent wrote, including the question and the
options it laid out.

## 2. Make the call

Read the blocker and decide. If the plan was ambiguous, edit the plan so the
decision is captured for next time.

## 3. Resume as a HITL run

Re-run the plan in your interactive agent so you can answer the open decision as
the agent reaches it. Land onto the same holding branch the rest of the batch uses:

```
/mentat-implement run --land --holding holding/feature wedged-plan
```

Because you are now in the loop, the run stops at the decision point for your answer
instead of wedging again. The preserved worktree means the agent resumes from where
it stopped rather than from scratch.

## Fresh-agent continuity

The same `summary.md` file is the handoff mechanism behind agent continuity. When
a run's token usage crosses the configured `compaction_threshold_tokens`, Mentat
writes a checkpoint `summary.md` with `status: succeeded` and the next spawn is
seeded with it — a fresh agent continues the work instead of compacting context in
place. A wedge and a checkpoint use the same file and differ only by `status:`. See
[ADR-0013](../adr/0013-agent-continuity-over-compaction.md).

## Notes

- The summary `status:` vocabulary is the contract: `succeeded`, `failed`,
  `blocked`. A wedge is `blocked`; the audit payload records the same intent as
  hitl-required.
- A wedged worktree is never torn down automatically — it holds work waiting on your
  decision.
