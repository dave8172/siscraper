"""Sweep many candidate paths across many hosts, in parallel, and keep little.

The expensive mistake is guessing one URL per host and believing the 404. Half
of this method's value showed up as hosts a single guess had already written
off: nine of eighty-six records in the pass that produced this tool were on a
path the first guess missed.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .extract import score
from .fetch import Fetcher
from .text import to_text


@dataclass
class Hit:
    host: str
    url: str = ""
    path: str = ""
    score: int = 0
    status: int = 0
    diagnosis: str = ""
    attempts: list = field(default_factory=list)   # every path tried, in order
    gave_up: int = 0      # paths abandoned after the host kept refusing

    @property
    def found(self) -> bool:
        return bool(self.url)


def landed_on_root(path: str, final_url: str) -> bool:
    """Did a request for a real path end up at the site's front door?

    A large minority of sites answer any unknown path with a 301 to `/`
    rather than a 404, and a homepage that says "Affiliates" in its footer
    scores like a terms page. This is the sharpest form of "a 200 means
    nothing" (seed/RULES.md §2): the status is 200, the body is real, and
    the page is simply not the one that was asked for.

    Deliberately narrow. A redirect from `/affiliates` to
    `/affiliate-program/` is a site being helpful and must still count; only
    landing on the root is treated as a miss.
    """
    if path.strip("/") == "":
        return False
    return (urlparse(final_url).path or "/").strip("/") == ""


# Diagnoses that say the host is refusing to talk, rather than answering.
# The distinction matters here for a different reason than in memory: these
# are the ones that will still be true on the next path.
_REFUSALS = frozenset({"rate-limited", "cloudflare-interstitial", "forbidden",
                       "timeout", "robots-disallowed"})


def probe_host(host, paths, keywords, fetcher=None, weights=None,
               min_score=1, stop_at=None, escalate=False, give_up_after=3):
    """Try `paths` on `host`, return the best-scoring page.

    `stop_at` is the early-exit score. It is a real trade: exiting early saves
    requests but stops you learning whether a later path would have scored
    higher, which is the data that tunes the path order. Leave it None on a
    pass whose purpose is to learn.

    `give_up_after` is the opposite trade and is not optional at scale. A host
    that has refused three times in a row will refuse the rest, and under the
    429 backoff each further attempt costs *more* than the last -- one strict
    host can hold a worker for ten minutes while hundreds wait. Only refusals
    count toward it: a run of 404s is the host answering, and that is exactly
    the case the sweep exists to work through.
    """
    fetcher = fetcher or Fetcher()
    best = Hit(host=host)
    scheme = "https"
    refused = 0
    for path in paths:
        url = f"{scheme}://{host}{path}"
        r = fetcher.get(url, escalate=escalate)
        bounced = r.ok and landed_on_root(path, r.final_url or url)
        text = "" if bounced else (to_text(r.body) if r.body else "")
        s = score(text, keywords, weights) if r.ok and not bounced else 0
        best.attempts.append({
            "path": path, "status": r.status,
            "diagnosis": "redirected-to-root" if bounced else r.diagnosis(),
            "score": s,
        })
        if r.ok and not bounced and s >= min_score and s > best.score:
            best.url, best.path, best.score = r.final_url or url, path, s
            best.status, best.diagnosis = r.status, r.diagnosis()
        if not best.diagnosis:
            best.diagnosis = best.attempts[-1]["diagnosis"]
        if stop_at is not None and s >= stop_at:
            break
        refused = refused + 1 if best.attempts[-1]["diagnosis"] in _REFUSALS else 0
        if give_up_after and refused >= give_up_after:
            # Recorded on the hit, never as an attempt. `attempts` is the
            # denominator for path win rates, and a path nobody tried must
            # not appear in it (seed/RULES.md §11).
            best.gave_up = len(paths) - paths.index(path) - 1
            break
    return best


def probe_many(hosts, paths, keywords, workers=8, **kw):
    """Parallel across hosts, never within one host -- that is what the
    per-host rate limit in Fetcher is protecting."""
    fetcher = kw.pop("fetcher", None) or Fetcher()
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(probe_host, h, paths, keywords,
                               fetcher=fetcher, **kw) for h in hosts]
        for f in futures:
            results.append(f.result())
    return results


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()
