# Scraping rules — the things counting can never tell you

**This file ships with every copy of siscraper and is read by whoever interprets results — a person or an agent. It is not executed.**

*This is the craft: how pages fail, and what it costs to find out. How the tool is built and why its memory is split three ways is `docs/architecture.md` in the source repo. Neither file should grow into the other.*

Host facts live in `hosts.json`, path rates in `paths.json`, and both are written by the tool. What is here is judgment: the failures that look like other failures, and the costs that are invisible until you have paid them once. Append when a pass teaches something that generalises across hosts. Anything true of only one host belongs in memory, not here.

---

## 1. The scarce resource is reading, not requests

A sweep of three hundred domains costs minutes and nothing else. Reading what comes back is what actually costs. **Design every step to hand the next one less**: score before reading, subtract boilerplate before returning lines, cap output by default.

Consequence: an early-exit threshold is a real trade, not a free optimisation. Exiting at the first good-enough page saves requests but destroys the evidence of whether a later path would have scored higher — which is the only input to path tuning. **On a pass whose purpose is to learn, do not set `stop_at`.**

## 2. A `200` means nothing

Plenty of sites answer any unknown path with a catch-all page. Status tells you the request completed; it does not tell you the page exists. **Keyword scoring is what separates them**, and it costs no extra request because the body is already in hand.

Corollary: never write "found" into memory on a status code alone.

**The sharpest version of this is the catch-all redirect.** A large minority of
sites answer an unknown path with a `301` to `/` rather than a `404` — so the
request for `/affiliates` returns 200, a real body, and a homepage whose footer
says "Affiliates". It scores like a terms page and it is not one. Compare the
path you asked for against the path you landed on: **landing on the root is a
miss.** Keep the test narrow — `/affiliates` → `/affiliate-program/` is a site
being helpful, and must still count.

## 3. Distinguish the ways a page fails

**A script-rendered shell is a *successful* fetch.** 200, no error, no redirect — and nothing on the page. That is exactly why "did the request succeed" must never be what ends an escalation ladder: the request did succeed. The page is simply not there yet. This tool shipped with that bug for an hour; it returned a Podia page with 65KB of HTML and sixteen characters of text, and reported the terms as missing.

They look identical from the outside and mean opposite things:

| Looks like | Actually is | What to do |
|---|---|---|
| Empty answer | Vendor genuinely does not publish it | **Record it.** A stated absence is a finding. |
| Empty answer | Content rendered by script after load | Escalate a rung |
| Empty answer | A 200 carrying no document at all | Record `empty-body`. A browser renders nothing either — escalating buys nothing. |
| Blocked | Cloudflare interstitial | Escalate, then give up — headless does not clear it |
| Blocked | Cloudflare *throttling*, which serves the same page with a 429 | Back off and retry once. It clears; an interstitial does not. |
| Blocked | robots-disallowed | Do not escalate. Respect it. |

**The last two are the same page.** Cloudflare returns "Just a moment…" both
when it is challenging you and when it is rate-limiting you, and only the
status code separates them — so **test the status before the body**. Read one
as the other and you either abandon a reachable host forever or keep hammering
a wall.

**This is the single most important distinction in the tool.** On the pass that produced siscraper, several vendor pages posed a question ("What is the cookie duration?") whose answer lived in an accordion that never rendered. Treating that as "not published" would have been a fabricated fact; treating a genuine silence as a fetch bug would have hidden a real finding.

## 4. Boilerplate contains the word you are searching for

Search a page for `cookie` and you will mostly find cookie-consent banners. Search for `payment` and you will find the footer's payment-method icons. **Noise must be subtracted after matching, never before** — and the noise list is worth more than any single pattern in the want-list. `seed/noise.json` carries the starting set.

The corollary bites in the other direction too: a nav item reading "PayPal" is not a payout method, and an integrations menu listing "Stripe" is not a payout method either. **Proximity is not evidence.**

**And it bites a third way, which cost a false positive on this tool's first real run.** A noise list tuned to kill consent banners will eventually kill a *real* sentence containing the same words. One vendor answers "What is your referral cookie policy?" with the actual window — and a pattern matching `cookie policy` deleted the answer. Hence `protect`: a line carrying real signal (a percentage, an amount, a day count) survives noise. **Noise should only remove lines that are nothing but boilerplate.**

## 5. The stdlib will quietly refuse to fetch anything

`urllib.robotparser.RobotFileParser.read()` sends Python's default User-Agent. A large number of sites answer that with a 403 — and the parser reads a 403 on `robots.txt` as **disallow-all**. The same file returns 200 under a browser UA.

Left alone this silently blocks nearly every fetch, and it looks like politeness rather than a bug. Fetch `robots.txt` yourself with a real UA, parse the text, and treat an unreadable file as permission rather than a ban. **An unreadable robots.txt is not a ban; a readable one that says no is.**

## 6. Guessing one URL per host is the expensive mistake

Sweeping thirteen paths costs twelve extra cheap requests. On the pass that produced this tool, **nine of eighty-six records came from hosts a single guessed URL had already written off as dead** — live all along, at a different path.

Measured, `/affiliates` and `/partners` won most often, and `/partners` was ranked fifth by guesswork. **Order paths by measurement, never by intuition** — that is what `paths.json` is for.

## 7. A structurally perfect hit can be semantically the wrong page

`fastspring.com/affiliates` scores beautifully and is about running *your own* affiliate programme, not joining theirs. Vendor "partner" pages routinely mean reseller, agency, integration, or investor.

**Scoring finds candidate pages. It does not read them.** Something with judgment has to confirm the page answers the question asked.

## 8. Self-healing means detect and refuse, never patch

When extraction stops matching, the tempting repair is to loosen the pattern until data flows again. **Do not.** A scraper that loosens its own matching produces *wrong* data instead of *no* data, and wrong data is unrecoverable downstream — nobody can tell a fabricated number from a real one after the fact.

Mark the host stale, say so, and stop. A consumer can act on "this went stale". Nobody recovers from a plausible number that is quietly false.

## 9. Parallelism is not politeness

Fourteen workers across eighty hosts is considerate. Fourteen aimed at one host is an attack. **Rate-limit per host and parallelise across hosts** — they are separate settings for a reason.

## 10. A 429 is the host telling you your rate is wrong

Believe it, and slow that host down for the **rest of the run** rather than
for one request. Retrying at the same pace is how one throttled host becomes a
whole sweep of them.

It is also worth exactly one retry. A host still refusing after you have
honoured its own `Retry-After` is not going to yield to persistence, and a
sweep always has hundreds of other hosts to spend that time on.

**And it needs a circuit breaker, because backoff alone gets worse the longer
it runs.** Each successive 429 slows that host further, so a strict host
sweeping twenty paths costs more with every attempt — one of them can hold a
worker for ten minutes while hundreds of hosts wait. Three refusals in a row
and the host is done for this pass. Count only *refusals*: a run of 404s is
the host answering, and working through those is the entire point of a sweep.

Note what a throttle is *not*: evidence about whether the host has what you
wanted. It answered a question you did not ask. Writing "nothing here" from a
429 invents a verdict; writing "blocked" refuses to ask again for months over
a condition you caused. Record it as its own state.

## 11. Record every attempt, not just the winner

Logging only the path that worked makes win *counts* computable and hit *rates* impossible, because the denominator is gone. It cannot be backfilled — the requests are spent.

The pass that produced this tool made exactly this mistake, which is why `seed/paths.seed.json` carries `won` counts with `tried: 0`. Do not repeat it.

## 12. A miss is two facts, and only one of them is a block

A sweep that finds nothing has two completely different causes, and the
difference decides whether you should ever ask again:

- **Every path 404s.** The host answered every time. It is reachable, and the
  paths were wrong. This is a *task outcome*, and it must be retried the moment
  the path list grows or the task changes.
- **Nothing answered at all** — interstitial, timeout, DNS, refused. This is a
  *reachability* fact, and it is worth not paying for twice.

Recording the first as "blocked" is not a cosmetic error. Skip logic then
refuses to spend a request on a perfectly reachable host until the verdict ages
out, so a vendor whose programme simply sits at a path nobody guessed becomes
invisible — **and it looks like memory working rather than memory lying**,
which is why it survives review. The counts even improve, because the hosts
that would have lowered them are no longer sampled.

The same asymmetry runs through §3: what a failure *means* determines the
response, and status alone never carries the meaning.

## 13. What belongs where

- A fact about **one host's reachability** → `hosts.json`. Universal; the only host knowledge that ships in the seed.
- A fact about **one host, for one task** ("no programme here") → local memory. One project's finding.
- A number **derived by counting** → `paths.json`, recomputed, never typed.
- Everything else → this file.

Prose that could have been a keyed lookup is the failure mode. On the pass before this tool existed, the blocked-host list was written in prose — so a human had to read it and apply it by hand, and nine hosts were wrongly written off anyway. **Knowledge a program can apply should never be stored as prose.**
