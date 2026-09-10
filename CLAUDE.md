# siscraper — notes for agents

Full documentation is in [`README.md`](README.md). Do not duplicate it here.

**Read before changing anything:**

| | |
|---|---|
| [`README.md`](README.md) | what it is, how to use it, the layout |
| [`docs/architecture.md`](docs/architecture.md) | the design — three kinds of knowledge, why they are split, how a run flows |
| [`seed/RULES.md`](seed/RULES.md) | the craft — how pages fail and what it costs to find out. **Read before interpreting any output.** |
| [`docs/shared-learning.md`](docs/shared-learning.md) | the unbuilt design for pooling learnings across deployments |

## Invariants — breaking one breaks the design

1. **`paths.json` is derived, never edited.** Change the run log and recompute.
2. **Log every attempt, not just the winner.** Rates need denominators and cannot be backfilled.
3. **Detect and refuse, never patch.** When extraction stops matching, mark the host stale and stop. Loosening a matcher to keep data flowing produces wrong data instead of no data.
4. **Never a runtime dependency of a shipped artifact.** This is an authoring tool.
5. **Universal facts go in `seed/`, contextual ones stay in `memory/`.** When unsure, local.
6. **The escalation ladder must not end on "the request succeeded".** A script-rendered shell is a successful fetch with nothing on the page.

## House style

- Python 3.11+, **standard library only**. No dependencies, ever — it has to vendor into any project with no install step.
- Comments explain *why*, especially where a line encodes a lesson that cost something to learn. Those are the point of the file.
- `python3 -m tests.test_core` before committing. No network required.
