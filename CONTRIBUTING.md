# Contributing

Bug reports, fixes and rules are all welcome. There is one rule that decides
more pull requests than the rest combined, so it goes first.

## The scoping rule: siscraper knows about scraping, and nothing else

**Every change must earn its place by being true of pages, hosts, or the tool
itself — never by being needed for one project that uses it.**

siscraper is written by being used. Its best rules came out of real
data-gathering passes, and that is how it should keep working: a consumer
project hits something, and the general lesson comes back here. But *where a
fix was discovered* and *what the fix is allowed to know* are different
questions, and only the second one matters.

The test, before you open a PR:

> Would a scraper doing a completely unrelated job — a job board, a parts
> catalogue, a council planning portal — still want this?

If yes, it belongs here. If it only makes sense once you know what the
consuming project is collecting, it belongs in the consuming project.

### Concretely

**Belongs in siscraper** — how pages fail, how hosts behave, how the tool
should behave:

- fetch, escalation, rate limiting, backoff, robots handling
- diagnosing *why* a page yielded nothing (missing, blocked, throttled,
  script-rendered, empty, bounced to the root)
- how text is extracted, how boilerplate is subtracted, how output is capped
- how memory is split, written, derived and read
- a prose rule in `seed/RULES.md` that generalises across hosts

**Belongs in the consumer** — anything downstream of "this page is worth
reading":

- the want-list and score weights for one subject
- the record schema, the category enum, the validator
- which page actually answers the question (`seed/RULES.md` §8 — scoring finds
  candidate pages, it does not read them; that judgement is the consumer's)
- that host's task outcome: "no programme here", "wrong page", "closed down"
- anything shaped like a dataset

### The line that will trip you up: a task is not a consumer

`seed/paths.seed.json` is namespaced **by task**, and task-level measurement is
welcome in the seed. `affiliate-terms` is a task any project could run and any
project could benefit from; a specific project that happens to run it is not.
Contribute the path rates, not the project.

The same distinction runs through `memory.py`: host *reachability* is universal
and ships in the seed; a host's *outcome for one task* stays local. When you
are unsure which side something is on, it is local — the seed is cheap to add
to and expensive to un-pollute.

### Why this is a hard rule and not a preference

The whole design is that a copy of this tool can be dropped into any project
with no install step and no context to inherit. A tool that has absorbed one
consumer's specifics is no longer copyable: the next project has to read around
somebody else's problem to find out what applies to theirs, and the seed —
which is supposed to stay small forever — starts growing with every consumer
that touches it.

This is the mirror of rule 4 in the README. That one says the consumer must
never depend on siscraper at runtime. This one says siscraper must never depend
on the consumer at all. One boundary, two directions, and both of them fail
quietly rather than loudly.

## What may enter `seed/`

The scoping rule above says what belongs in the repository. This says what
belongs in the part of it that **every clone inherits**.

`seed/` carries only what is true regardless of what you were scraping:

- **prose rules** — how scraping fails, in `seed/RULES.md`
- **noise patterns** — boilerplate that is boilerplate everywhere
- **host reachability** — *"this host serves a JS shell that headless does not
  clear"* is true whatever you wanted from it

**Task outcomes and path rates are not universal and do not go here.** They
live in the consuming project's `memory/`, which is exactly what that directory
is for.

It is worth saying plainly because the mistake is a reasonable one, and was
made here: a project measured its path win-rates over thousands of requests,
and a measured order genuinely does beat a guessed one — so the numbers were
copied into the seed as a gift to the next person. Two things wrong with it.
Those rates are **meaningless to anyone scraping something else**, and they are
**one consumer's work handed to every other**, including whoever that consumer
is competing with. `seed/paths.seed.json` ships `{}`.

The test for anything proposed for `seed/`: *would this still be true for
someone scraping a completely different kind of page?* Reachability survives
that question. A win-rate for `/affiliates` does not.

## The rest

- **Read [`docs/architecture.md`](docs/architecture.md) first.** Most rejected
  changes are ones that collapse two of the three kinds of knowledge.
- **Read [`seed/RULES.md`](seed/RULES.md) before changing extraction or
  diagnosis.** Several of those rules exist because something plausible was
  tried and produced wrong data rather than no data.
- **Honour the invariants** in the README's "Rules for working on this". They
  are not style; each one describes a specific way this design stops working.
- **Standard library only.** Python 3.11+, no dependencies, ever — it has to
  vendor into any project with no install step.
- **`python3 -m tests.test_core` before committing.** No network needed. A bug
  worth fixing is usually worth a test that names the failure in English.
- **Comments explain *why*.** Where a line encodes a lesson that cost something
  to learn, say what it cost. Those comments are the point of the file.

## Reporting something without fixing it

An issue saying "this host does X and the tool concluded Y" is genuinely
useful, especially when Y looked correct. The most expensive bugs found so far
all shared that shape: the tool reported success, the numbers even improved,
and the data was wrong.
