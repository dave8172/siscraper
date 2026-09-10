# siscraper — a self-improving scraper

**What it is:** a small, copyable scraping toolkit that gets better at its job every time it runs. Zero dependencies, Python 3.11+ stdlib only.

**Why it exists:** built out of a real data-gathering pass, after noticing the same scraping lessons being re-derived for the third time across unrelated scripts — one of them had independently rediscovered a rule another had written down months earlier. The code was never the expensive part; the knowledge was.

## The idea in one paragraph

Three kinds of knowledge, separated by **who writes them and whether they can be recomputed**. The tool writes what it observes (`hosts.json`), derives what it can count (`paths.json`), and reads what only judgment can supply (`seed/RULES.md`). Collapsing these is what makes scraper knowledge rot — knowledge a program could apply gets stored as prose, and then a human has to apply it by hand.

**Full explanation: [`docs/architecture.md`](docs/architecture.md).**

## Copyable, not central

There is no shared server and no central store — that would grow without bound and couple every consumer together. Instead:

| | Where | Grows | Shipped with a copy |
|---|---|---|---|
| **Seed** | `seed/` | Barely | **Yes** — curated |
| **Local memory** | `memory/` | Fast | No — per project |

The seed carries only what is **universal**: the prose rules, the noise filters, and host **reachability** — "namecheap.com serves a Cloudflare interstitial that headless does not clear" is true regardless of what you wanted from it. That is why the shared part stays small forever: most hosts are simply reachable, so there is nothing to record.

Everything **contextual** stays local: task outcomes ("BigCommerce closed its affiliate programme" is one project's finding) and path win-rates (`/affiliates` rates mean nothing to a job-board scraper — so `paths.json` is namespaced by task).

**Read order is local first, seed as the floor.** Nobody starts at zero; nobody inherits another project's context.

Promotion of a local finding back into the seed is deliberately **manual and unbuilt** — it only matters at three or more consumers, and automating it early is how the seed stops being curated.

## Use it

```bash
python3 -m siscraper init /path/to/project   # vendor into .siscraper/
python3 -m siscraper known namecheap.com     # what's known before spending a request
python3 -m siscraper probe --task affiliate-terms acme.com …
python3 -m siscraper read https://x.com/affiliates --want 'cookie,payout,\d+ ?%'
python3 -m siscraper recompute --task affiliate-terms
```

```python
from siscraper import Session
s = Session("affiliate-terms", root=".siscraper")
hits, skipped = s.sweep(hosts, keywords=["affiliate", "commission", "cookie"])
lines, resp = s.read(hits[0].url, want=[r"\d+ ?%", "cookie", "payout"])
```

## Using it responsibly

It respects `robots.txt` by default and rate-limits per host. Both are on unless you turn them off, and turning them off is your decision to own. Parallelism is across hosts, never within one — fourteen workers over eighty hosts is considerate, fourteen aimed at one host is not.

The seed ships knowledge about *reachability*, not about how to get around anything. If a site says no, the correct outcome is a recorded "no".

## Layout

| Path | What |
|---|---|
| `siscraper/fetch.py` | fetch + escalation ladder + per-host rate limit + robots |
| `siscraper/text.py` | HTML → readable lines |
| `siscraper/extract.py` | keyword lines, noise subtracted, capped |
| `siscraper/probe.py` | parallel path sweep with scoring |
| `siscraper/memory.py` | seed + local layering; the self-improving part |
| `seed/RULES.md` | **read this before interpreting any output** |
| `seed/*.seed.json` | universal reachability, noise filters, starting path order |
| `memory/` | this repo's own working memory |
| `docs/architecture.md` | **the design explained** — the three kinds of knowledge, why they are split, how a run flows through |
| `docs/shared-learning.md` | unbuilt design for pooling learnings across deployments |

## Rules for working on this

1. **`paths.json` is derived, never edited.** The moment a number is typed into it you can no longer tell measurement from guesswork. Change the run log and recompute.
2. **Log every attempt, not just the winner.** Rates need denominators and they cannot be backfilled.
3. **Detect and refuse, never patch.** When extraction stops matching, mark the host stale and stop. A scraper that loosens its own matching produces wrong data instead of no data, and wrong data is unrecoverable downstream.
4. **Never a runtime dependency of a shipped artifact.** siscraper is an authoring tool. The consuming project should ship its data and its own build; siscraper produces the data and disappears. Anything handed to someone else must not carry a dependency they cannot be given.
5. **Universal facts go in the seed, contextual ones stay local.** When unsure, local — the seed is expensive to un-pollute.

## Status

**v0.1.1, working.** Seeded from a real pass: 13 reachability records, 16 noise patterns, win-counts for 13 paths drawn from ~130 successful sweeps, and 13 rules. 31 tests, no network needed (`python3 -m tests.test_core`).

**v0.1.1 came out of the first sweep large enough to hurt** — 400+ hosts for its first consumer. Four failures that a small pass never surfaces:

| Found | Fixed by |
|---|---|
| A catch-all `301` to `/` scored like a terms page, because the homepage footer says "Affiliates" | `landed_on_root` — compare the path you asked for with the one you landed on |
| A sweep where every path 404s was written to memory as **blocked**, so a reachable host whose page sits at an unguessed path was skipped for 90 days | `Session._record_miss` — a miss is a task outcome unless nothing answered at all |
| Cloudflare serves the same "Just a moment…" page when **throttling** (429) as when challenging, and the two mean opposite things | status is tested before the body; a 429 backs off, penalises that host's interval, and retries once |
| Backoff alone gets worse the longer it runs: one strict host held a worker for ten minutes | `give_up_after` — three refusals in a row ends the host. 404s do not count; those are answers |

Each is now a rule in `seed/RULES.md` (§2, §3, §10, §12) as well as code, because the next consumer will hit them before it reads the source.

Verified end to end against five hosts whose correct URLs were known by hand; all five matched, and a sixth was skipped from seed memory without spending a request.

**Known gap, inherited from the seeding pass:** `seed/paths.seed.json` carries `won` counts with `tried: 0` — that pass logged only winners, so the denominators are gone for good. Locally-computed rates supersede them as soon as any consumer runs a sweep.

**Exploration:** `Session(explore=0.1)` retries a tenth of the hosts memory says to skip, deterministic per host and day. Without it a scraper that trusts its memory can only ever lose hosts — a site that starts allowing traffic again is never noticed.

**Not built, deliberately:** promotion tooling, run-log compaction, caching, retry/backoff policy, proxy rotation, a config file. Add when a real consumer needs one, not before.

**Shared learning** — separate deployments pooling what they learn, so every copy improves from any copy's work — is designed but unbuilt. `docs/shared-learning.md` records the shape, the trust model, and the failure mode that decides whether it can work at all. It should wait for a third deployment.
