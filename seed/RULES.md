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

## 5. The spec table splits the answer away from the question

The most structured data on a vendor page is usually a two-column table, and
after HTML-to-text it is two consecutive lines:

    Cookie window
    90 days
    Minimum payout
    $150

Only the *label* matches a want-list. A line-at-a-time extractor returns the
questions and discards every answer — and the page then looks like it
published nothing, which is the one conclusion that must never be reached by
accident (§3). **Keep a line of trailing context after each match.** It cost
one page in this tool's first large pass to notice, and that page turned out
to publish its rate, duration, cap, frequency, method and threshold — all of
them in the column the extractor was throwing away.

Trailing context is not a match. Count it separately, or the hit counts stop
meaning anything.

## 6. A redirect to the same URL is a cookie gate, not a loop

Plenty of sites answer the first request with a `301` whose `Location` is **the
URL you just asked for**, plus a `Set-Cookie` — a language or region gate. With
no cookie jar that is an infinite redirect, and the stdlib gives up and reports
it as a plain `301`. It looks like a dead link. It is a page that works
perfectly in any browser.

Two things are needed, and one alone is not enough:

- **A cookie jar.** `http.cookiejar` is stdlib, so this costs nothing.
- **A short warm-up, not one retry.** A site needs one round trip per cookie
  it wants, and each attempt banks another — `snov.io` wants two and lands on
  the third call. One retry looked like enough and was not, intermittently,
  which produced something worse than a failure: a consumer judged a submitted
  figure against a 67-character redirect page and reported the claim false.
  **A half-fixed fetch turns "I could not read this" into "you are wrong",**
  which is the same class of error as §3 and costs more. Bound it hard; a
  genuine loop still stays a loop and gets reported as one.

Diagnose it as its own thing. `http-301` tells whoever reads the run log
nothing; `redirect-loop` tells them to look at cookies.

## 7. The stdlib will quietly refuse to fetch anything

`urllib.robotparser.RobotFileParser.read()` sends Python's default User-Agent. A large number of sites answer that with a 403 — and the parser reads a 403 on `robots.txt` as **disallow-all**. The same file returns 200 under a browser UA.

Left alone this silently blocks nearly every fetch, and it looks like politeness rather than a bug. Fetch `robots.txt` yourself with a real UA, parse the text, and treat an unreadable file as permission rather than a ban. **An unreadable robots.txt is not a ban; a readable one that says no is.**

## 8. Guessing one URL per host is the expensive mistake

Sweeping thirteen paths costs twelve extra cheap requests. On the pass that produced this tool, **nine of eighty-six records came from hosts a single guessed URL had already written off as dead** — live all along, at a different path.

On that pass the path ranked fifth by guesswork turned out to be among the top two by measurement. **Order paths by measurement, never by intuition** — that is what `paths.json` is for, and it is local because the ranking is only true for the thing you were looking for.

## 9. A structurally perfect hit can be semantically the wrong page

`fastspring.com/affiliates` scores beautifully and is about running *your own* affiliate programme, not joining theirs. Vendor "partner" pages routinely mean reseller, agency, integration, or investor.

**Scoring finds candidate pages. It does not read them.** Something with judgment has to confirm the page answers the question asked.

## 10. Self-healing means detect and refuse, never patch

When extraction stops matching, the tempting repair is to loosen the pattern until data flows again. **Do not.** A scraper that loosens its own matching produces *wrong* data instead of *no* data, and wrong data is unrecoverable downstream — nobody can tell a fabricated number from a real one after the fact.

Mark the host stale, say so, and stop. A consumer can act on "this went stale". Nobody recovers from a plausible number that is quietly false.

## 11. Parallelism is not politeness

Fourteen workers across eighty hosts is considerate. Fourteen aimed at one host is an attack. **Rate-limit per host and parallelise across hosts** — they are separate settings for a reason.

## 12. A 429 is the host telling you your rate is wrong

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

## 13. Record every attempt, not just the winner

Logging only the path that worked makes win *counts* computable and hit *rates* impossible, because the denominator is gone. It cannot be backfilled — the requests are spent.

The pass that produced this tool made exactly this mistake, which is why `seed/paths.seed.json` carries `won` counts with `tried: 0`. Do not repeat it.

## 14. A miss is two facts, and only one of them is a block

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

## 16. Precision and recall want opposite windows

Finding a value and detecting that the page contradicts it are different searches, and running both at one window size gets one of them wrong.

A **value** is found in a narrow window, because proximity is what makes it the right value rather than some other number on the page. A **contradiction** must be hunted across the whole document, because the competing statement is usually nowhere near the first one.

Measured: a vendor page stated a 30-day holding period near the top and its real 365-day attribution window much further down. A window-sized search saw one of them and published it **with confidence** — the safety rule was "two distinct values means a human decides", and it was worth nothing because the second value was out of frame.

Find in a window. Contradict across the document.

## 17. The boilerplate can be the *majority* of the matches

Rule 4 says boilerplate contains the word you are searching for. The sharper version: on a typical page it contains that word **more often than the content does**.

Most occurrences of "cookie" on a vendor page are the consent banner and the privacy policy, not the attribution window. So it is not enough to find a match and read near it — each match has to be classified and the boilerplate ones thrown away *before* any number is read out. A "30-day" anything near a cookie notice otherwise becomes a published attribution window.

Two cheap classifiers that worked: the match's window contains consent vocabulary and no domain vocabulary → discard it; the match is in a run of matches at a uniform depth → it is a nav or a policy block.

## 18. The keyword says nothing when the vendor sells that thing

"Recurring" appears on every line of a page belonging to a company whose product is recurring billing. The word being present carries no information about the terms.

A keyword is evidence only in proportion to how surprising it is on that particular page. Where a term is also the vendor's product category, require it to co-occur with the thing you are actually asking about, or drop it as a signal.

## 19. Negation, and substrings that swallow your needle

Two failures from the same run, both silent, both trivially avoidable:

- **"We do not offer recurring referrals"** contains the word and means the opposite of it. Any keyword extractor needs the negated forms listed, or it will confidently report the inverse.
- **"RecurPost Affiliate Program"** contains the string "Post Affiliate Pro" and was matched as that vendor. Word boundaries are not a nicety.

## 20. Value, silence, and refusal are three answers, not two

An extractor that returns a value or null is lying about one of two very different states: *the page does not say* and *the page says two things*.

Collapsing the second into null publishes a false claim — "not stated" about a vendor that did state it. Keep them apart, publish the silence, and route the refusal to a reader. **Refusal is the honest answer, not a failure mode to minimise.**

## 21. Score the extractor on the bucket that ships, not the average

An extractor measured against hand-written ground truth looked reasonable: 215 of 289 fields agreed. The number that mattered was different — of the records it was willing to publish *unsupervised*, **11% carried a figure the ground truth contradicts**.

Overall accuracy averages the easy cases in with the ones that reach production. Measure the error rate inside the set that would actually ship unreviewed; that is the number that decides whether the gate can move.

And keep the harness: the calibration set is a cache of page text keyed by record, so re-measuring after a pattern change costs nothing and refetches nothing.

## 15. What belongs where

- A fact about **one host's reachability** → `hosts.json`. Universal; the only host knowledge that ships in the seed.
- A fact about **one host, for one task** ("no programme here") → local memory. One project's finding.
- A number **derived by counting** → `paths.json`, recomputed, never typed.
- Everything else → this file.

Prose that could have been a keyed lookup is the failure mode. On the pass before this tool existed, the blocked-host list was written in prose — so a human had to read it and apply it by hand, and nine hosts were wrongly written off anyway. **Knowledge a program can apply should never be stored as prose.**
