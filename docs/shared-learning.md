# Shared learning — design note, not a build

**Status: not built. Deliberately.** This records the shape and the things that decide whether it works, so the reasoning is not re-derived later. If it is ever built, start here.

**The idea.** Separately deployed siscrapers contribute what they learn back to a shared seed, which redistributes to everyone, so every deployment improves from any deployment's work. One machine's wasted minute discovering that a host is unreachable becomes everyone's saved minute.

It is a genuinely good fit for this tool, because what siscraper accumulates is already **counts and short enums** — the two things that aggregate cleanly and travel in a few bytes. A deployment's entire contribution after a large pass is a few kilobytes.

But the naive version gets *worse* over time, and it takes a specific mechanism to stop that. That mechanism is the one piece already built.

**What could be shared is (a) and (b) from [`architecture.md`](architecture.md) — host reachability and path rates. Not (c): prose rules are judgment, and they travel in a reviewed release, not a feed.**

---

## 1. The failure mode that decides everything: calcification

**A pooled memory can only ever lose hosts.** Every "blocked" verdict is permanent until it ages out; a site that starts allowing traffic again is never noticed, because everyone is skipping it on the shared seed's advice. The bigger and more trusted the pool, the fewer deployments ever retry, and the more confidently the system converges on a stale picture of the web.

This is not a small risk. It is the default outcome, and it makes shared learning **actively worse than no sharing at all** — an isolated deployment at least retries things eventually.

**The fix is an exploration quota**, and it is the one piece already built (`Session(explore=0.1)`): a fraction of sweeps deliberately ignore the consensus, retry a host memory says to skip, and report back. Deterministic per host and day, so retries are predictable rather than random.

It is justified at a single deployment — a local memory calcifies in miniature — which is why it already exists. But it is **load-bearing** for any shared version: without it, don't build this.

## 2. Share observations, never verdicts — and only negatives

Two rules, both about what a malicious or broken deployment can do to everyone else.

**Observations, not verdicts.** Never accept "namecheap.com is blocked". Accept "I tried namecheap.com and got a cloudflare-interstitial on 2026-09-10". A fact enters the shared seed only after **k independent reporters** agree. One deployment then cannot move anything, and the natural shape of the data — a count — is already what the aggregation needs.

**Negatives pool safely; positives do not.** This asymmetry matters more than it looks:

- Sharing *"this host blocked me"* is safe. Worst case, everyone skips something fetchable — and the exploration quota finds it again.
- Sharing *"this host works, here's the URL"* is a **redirection attack surface**. A poisoned positive sends every deployment to a URL of the attacker's choosing, and they will fetch it and parse it.

So: **pool blocks, not destinations.** Path *rates* are fine (they are counts over path shapes, not URLs). Specific winning URLs stay local.

## 3. What is actually worth sharing

| Signal | Shareable | Size | Why |
|---|---|---|---|
| Host reachability, negative | **Yes** | ~60 bytes | Universal; true regardless of task |
| Path win rates, per task | **Yes** | ~13 ints | Pure counting; pools beautifully |
| Noise patterns | Curated only | tiny | One bad regex silently blinds everyone |
| Task outcomes | **No** | — | "No affiliate programme here" is one project's finding |
| Winning URLs | **No** | — | Redirection surface (§2) |
| Prose rules | Review, not sync | — | Judgment; belongs in a release, not a feed |

The whole payload is **counts and short enums**. The whole payload stays in the low kilobytes, which is what makes small signals the right instinct rather than a compromise.

**Value scales with host overlap, and overlap is high within a task, low across tasks.** Everyone scraping affiliate terms hits the same few hundred SaaS sites; an affiliate scraper and a job-board scraper share almost nothing but reachability. **So pool per task namespace, not globally.**

## 4. Privacy is a real blocker to default-on

Which hosts you scrape reveals what you are building. For a public directory of affiliate terms that is harmless; for competitor monitoring it leaks strategy. Sharing must be **opt-in per task**, and the conservative mode is **confirmations only** — report outcomes for hosts already in the shared seed, never contribute discoveries. That gives up learning about new hosts from others, in exchange for leaking nothing about what you are working on.

## 5. Infrastructure: a git repo, not a server

The cheapest correct v1 has no server at all.

- **Contribute:** a deployment emits an aggregated counts file and opens a pull request.
- **Moderate:** PR review. `k`-of-`n` confirmation is checkable in CI.
- **Sync:** `git pull`. Free audit trail, free identity, free hosting, no uptime cost, no legal surface from operating a coordination service.
- **"Global sync time":** the right version of this is a **tagged seed release** everyone converges on — `seed v0.3` — with *jittered* pulls. A literal synchronised moment would just be a thundering herd, and the value is in converging on a common snapshot, not on a common instant.

Decay comes free: every record carries `last_seen`, and confirmations refresh it. A fact nobody has re-observed in a year should fall out of the seed rather than harden into folklore.

## 6. When to build it

**Not before three or more independent deployments exist**, because until then the shared seed is a curated file that one person edits — which is what it already is, and it works.

What keeps the door open costs nothing today and is already true:

- The run log is stable, append-only JSONL of attempts — the exact input an aggregator needs.
- `paths.json` is derived, never typed, so pooled counts merge by addition.
- Reachability is already separated from task outcomes in the seed/local split.
- The exploration quota exists (`Session(explore=...)`).

Nothing else should be built until a second deployment is actually running.
