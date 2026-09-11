# Architecture

The design answers one question: **when a scraper learns something, where does that knowledge go?**

Most scraping code answers it badly — the learning ends up as a comment, a hardcoded list, or nothing at all, and the next person re-derives it. siscraper exists because that happened three times over: one script had a comment recording exactly the fact about JavaScript-rendered pages that a later, unrelated pass spent an afternoon rediscovering.

The answer is that there is no single "where", because **there are three kinds of knowledge and they have nothing in common except the subject**.

---

## The three kinds

### (a) Host facts — what is true of one website

During the pass that seeded this tool, `namecheap.com/affiliates` returned a Cloudflare interstitial. Escalating to a real browser returned the same interstitial. That cost three requests and about a minute, and it is a fact about **one hostname**:

```json
"namecheap.com": {
  "reach": "blocked", "reason": "cloudflare-interstitial",
  "rung": "headless", "last_seen": "2026-09-10"
}
```

- **Written by:** the tool, automatically, on every run. No judgment involved.
- **Recomputable:** no. It is an observation. You cannot derive it; you can only make it again.
- **Read by:** the tool, via one keyed lookup *before* spending a request.
- **Ages:** yes, which is why `last_seen` is mandatory. A block from eight months ago says little. See `STALE_DAYS` and the exploration quota below.

**Why this must be a keyed store and not prose.** The pass before siscraper existed already produced a blocked-host list — written in a markdown file. It saved nothing, because a *human* had to read it, hold it in mind, and apply it by hand. Nine of the hosts on it turned out to be live at a different path. Same knowledge, unusable form.

> **Knowledge a program can apply must never be stored as prose.**

### (b) Tuned behaviour — what generally works, derived by counting

That pass swept thirteen guessed URL paths per host. Here is what actually won, across ~130 successful sweeps:

```
31  /affiliates
27  /partners
22  /affiliate-program
15  /affiliate
 …  the other nine paths: almost nothing
```

`/partners` came second. It had been *guessed* fifth. Ordering the sweep by measurement instead of intuition finds the page in fewer requests, and the ordering improves every time anyone runs it.

```json
"affiliate-terms": {
  "/affiliates": {"tried": 307, "won": 31},
  "/partners":   {"tried": 298, "won": 27}
}
```

- **Written by:** a counting pass over the run log. **Nobody types these numbers.**
- **Recomputable:** always, and it must be recomputed rather than edited. The moment a number is typed into `paths.json` you can no longer tell measurement from guesswork.
- **Read by:** the tool, to order its sweep.

**This is the self-improving part, and it requires no intelligence at all.** It is arithmetic over a log. The same mechanism should eventually replace the hand-set early-exit threshold: given outcomes, you can ask at what score a page actually turned out usable, rather than guessing 25.

**It depends entirely on the run log recording every attempt, not just the winner.** Logging only what worked makes win *counts* computable and hit *rates* impossible — the denominator is gone, and it cannot be backfilled because the requests are spent. The pass that produced this tool made exactly that mistake, which is why `seed/paths.seed.json` ships `won` counts with `tried: 0`.

### (c) Prose rules — what counting can never discover

All of these are real, all from the same pass:

- A vendor's page asks *"What is the cookie duration?"* and the answer lives in an accordion that never renders in static HTML. A blank answer therefore has **two opposite causes**: the vendor doesn't publish it (a publishable finding) or the fetch wasn't deep enough (a bug). No amount of counting separates them.
- Searching a page for `cookie` mostly returns cookie-consent banners. The filter that removes them was the highest-leverage line in the extractor — and it later deleted a real answer, because one vendor phrased it *"referral cookie policy"*.
- A `200` means nothing. Many sites serve a catch-all page for unknown paths.
- `fastspring.com/affiliates` scores beautifully and is about running *your own* affiliate programme, not joining theirs.

- **Written by:** a person or an agent, after a pass. It is judgment.
- **Recomputable:** no.
- **Read by:** whoever interprets results — never executed by the tool.

These live in **`seed/RULES.md`**, which is the most valuable file in the repo and the only one that cannot be regenerated.

---

## Why split it this way

The split is by **who writes it** and **whether it can be recomputed** — because those two properties determine the storage, the update path, and the trust model. Three different answers, three different files.

| | Writer | Recomputable | Consumer | Lives in |
|---|---|---|---|---|
| **(a)** Host facts | tool, automatic | no — observation | tool, keyed lookup | `hosts.json` |
| **(b)** Path rates | counting script | **always** | tool, sweep order | `paths.json` |
| **(c)** Prose rules | human / agent | no — judgment | human / agent | `seed/RULES.md` |

Merge any two and the surviving file loses the property that made it work:

- **(b) into (a)** — you cannot recompute without clobbering observations.
- **(c) into (a)** — prose in a keyed store: the program can't use it, and nobody recomputes prose, so it rots.
- **(a) into (c)** — the failure that motivated the whole tool: knowledge that exists but is never applied.

---

## The second axis: universal vs contextual

The three kinds say *what* a fact is. A second, independent question decides *where a copy keeps it*: *is this true for everyone, or only for me?*

**Seed — universal, ships with every copy, stays tiny.**
Prose rules, noise filters, and host **reachability**. "namecheap.com serves a Cloudflare interstitial that headless doesn't clear" is true regardless of what you wanted from the host. The seed cannot grow much even in principle, because **most hosts are simply reachable and there is nothing to record**.

**Local memory — contextual, grows in the consuming project, never shipped back.**
Task outcomes and path rates. "BigCommerce closed its affiliate programme" is one project's finding, not a universal fact. `/affiliates` win rates are meaningless to a job-board scraper, so `paths.json` is namespaced by task.

**Read order is local first, seed as the floor.** Nobody starts at zero; nobody inherits another project's context. A local success overrides a seed block outright, because local is both fresher and contextual.

```
      seed/  (universal, curated, ~13 hosts · 16 noise patterns · 11 rules)
        │  floor
        ▼
   memory/  (contextual, grows: a real consumer carries 132 hosts after one pass)
        │  local wins
        ▼
     lookup answers the question
```

---

## Copyable, not central

There is no server and no shared store. `python3 -m siscraper init <project>` vendors code plus the seed into `<project>/.siscraper/`, which then grows its own memory.

A copy, deliberately — not a package dependency or a git submodule. It installs with no network, no version resolution and no build step, and a project handed to someone else carries a **self-contained** tool rather than a reference to a repo they cannot reach. For anything that might be handed over, that is the difference between a self-contained asset and one carrying a dependency the recipient cannot be given.

Pooling learnings *across* copies is designed but unbuilt — see [`shared-learning.md`](shared-learning.md).

---

## How a run flows through it

```
hosts ──▶ Memory.known(host)          (a) — skip what is already answered
              │                             …unless the exploration quota fires
              ▼
          Memory.path_order(task)     (b) — measured order, seed as fallback
              │
              ▼
          probe_many ──▶ Fetcher.get ──▶ plain ──▶ [js-shell? interstitial?] ──▶ headless
              │                                          │
              │                                          └─ diagnosis, not just failure
              ▼
          to_text ──▶ score            a 200 is not evidence; keywords are
              │
              ▼
          extract(want, noise, protect)   the smallest set of lines that could hold an answer
              │
              ├──▶ Memory.record_reach / record_outcome   (a)
              └──▶ Memory.log_run  ──▶  recompute_paths   (b)
```

The last arrow is the loop closing: what this run observed changes how the next run sweeps.

**Exploration.** `Session(explore=0.1)` deliberately retries a tenth of the hosts memory says to skip, deterministic per host and day. Without it, memory can only ever *lose* hosts — every block is permanent until it ages out, and a site that starts allowing traffic again is never noticed. It matters at one node and is load-bearing for any shared version.

---

## Modules

| File | Responsibility |
|---|---|
| `fetch.py` | escalation ladder, per-host rate limiting, robots, **diagnosis** |
| `text.py` | HTML → readable, deduplicated lines |
| `extract.py` | keyword lines, noise subtracted, `protect` overriding noise, hard caps |
| `probe.py` | parallel path sweep across hosts, keyword scoring |
| `memory.py` | seed + local layering, run log, `recompute_paths` |
| `__init__.py` | `Session` — the memory-aware entry point tying the above together |
| `cli.py` | `init`, `known`, `fetch`, `read`, `probe`, `recompute` |

Parallelism is **across hosts only**. Fourteen workers over eighty hosts is considerate; fourteen aimed at one host is an attack. That is why the rate limit is per-host and the worker count is global — separate settings, separate purposes.

---

## Invariants

Break any of these and the design stops working:

1. **`paths.json` is derived, never edited.** Change the run log and recompute.
2. **Log every attempt, not just the winner.** Rates need denominators; they cannot be backfilled.
3. **Detect and refuse, never patch.** When extraction stops matching, mark the host stale and stop. A scraper that loosens its own matching produces *wrong* data instead of *no* data, and wrong data is unrecoverable downstream — nobody can tell a fabricated number from a real one afterwards.
4. **Never a runtime dependency of a shipped artifact.** siscraper is an authoring tool. The consuming project ships its data and its own build; siscraper produces the data and disappears.
5. **And never the reverse: nothing consumer-specific comes back in.** The tool is written by being used, so improvements arrive from whatever project is using it — but a change earns its place by being general, not by being needed. A copy that has absorbed one consumer's specifics is no longer copyable, which is the entire premise. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
6. **Universal facts go in the seed, contextual ones stay local.** When unsure, local — the seed is expensive to un-pollute.
7. **The escalation ladder must not end on "the request succeeded".** A script-rendered shell is a *successful* fetch with nothing on the page.

---

## Known limitation: one writer at a time

`memory/` is safe against a crash and unsafe against a sibling. Each `Memory`
holds the whole of `hosts.json` in memory and rewrites it atomically, so an
interrupted run never leaves a half-written file — but two processes sweeping
different hosts into the same `.siscraper` will each write their own complete
picture, and the last one to finish wins. Everything the other learned is
gone, silently, with no error and a perfectly valid file left behind.

This surfaced the first time a consumer wanted to halve a forty-minute run by
splitting it in two. **Run batches sequentially**, or give each parallel run
its own `root=` and merge afterwards. Parallelism *within* one run is fine:
that is threads sharing a single `Memory` behind its lock.

The fix — a lock file and read-modify-write on each dump — is small and
deliberately not built yet, on the same principle as everything else in the
not-built list. It costs a real run being slower, which is a smaller price
than a concurrency bug in the part of the tool whose whole job is to be
trusted.

---

## Related documents

- **[`../seed/RULES.md`](../seed/RULES.md)** — the (c) knowledge itself: fifteen operational rules about how pages fail and what it costs to find out. Read it before interpreting any output. Ships with every copy.
- **[`../CONTRIBUTING.md`](../CONTRIBUTING.md)** — where the line falls between this tool and the project using it, which is the question most changes actually turn on.
- **[`shared-learning.md`](shared-learning.md)** — the unbuilt design for pooling (a) and (b) across deployments, and the failure mode that decides whether it can work.

This file explains the *system*. `RULES.md` holds the *craft*. They do not duplicate each other, and neither should grow into the other.
