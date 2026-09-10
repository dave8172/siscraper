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

## 3. Distinguish the four ways a page fails

**A script-rendered shell is a *successful* fetch.** 200, no error, no redirect — and nothing on the page. That is exactly why "did the request succeed" must never be what ends an escalation ladder: the request did succeed. The page is simply not there yet. This tool shipped with that bug for an hour; it returned a Podia page with 65KB of HTML and sixteen characters of text, and reported the terms as missing.

They look identical from the outside and mean opposite things:

| Looks like | Actually is | What to do |
|---|---|---|
| Empty answer | Vendor genuinely does not publish it | **Record it.** A stated absence is a finding. |
| Empty answer | Content rendered by script after load | Escalate a rung |
| Blocked | Cloudflare interstitial | Escalate, then give up — headless does not clear it |
| Blocked | robots-disallowed | Do not escalate. Respect it. |

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

## 10. Record every attempt, not just the winner

Logging only the path that worked makes win *counts* computable and hit *rates* impossible, because the denominator is gone. It cannot be backfilled — the requests are spent.

The pass that produced this tool made exactly this mistake, which is why `seed/paths.seed.json` carries `won` counts with `tried: 0`. Do not repeat it.

## 11. What belongs where

- A fact about **one host's reachability** → `hosts.json`. Universal; the only host knowledge that ships in the seed.
- A fact about **one host, for one task** ("no programme here") → local memory. One project's finding.
- A number **derived by counting** → `paths.json`, recomputed, never typed.
- Everything else → this file.

Prose that could have been a keyed lookup is the failure mode. On the pass before this tool existed, the blocked-host list was written in prose — so a human had to read it and apply it by hand, and nine hosts were wrongly written off anyway. **Knowledge a program can apply should never be stored as prose.**
