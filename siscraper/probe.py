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

    @property
    def found(self) -> bool:
        return bool(self.url)


def probe_host(host, paths, keywords, fetcher=None, weights=None,
               min_score=1, stop_at=None, escalate=False):
    """Try `paths` on `host`, return the best-scoring page.

    `stop_at` is the early-exit score. It is a real trade: exiting early saves
    requests but stops you learning whether a later path would have scored
    higher, which is the data that tunes the path order. Leave it None on a
    pass whose purpose is to learn.
    """
    fetcher = fetcher or Fetcher()
    best = Hit(host=host)
    scheme = "https"
    for path in paths:
        url = f"{scheme}://{host}{path}"
        r = fetcher.get(url, escalate=escalate)
        text = to_text(r.body) if r.body else ""
        s = score(text, keywords, weights) if r.ok else 0
        best.attempts.append({
            "path": path, "status": r.status,
            "diagnosis": r.diagnosis(), "score": s,
        })
        if r.ok and s >= min_score and s > best.score:
            best.url, best.path, best.score = r.final_url or url, path, s
            best.status, best.diagnosis = r.status, r.diagnosis()
        if not best.diagnosis:
            best.diagnosis = r.diagnosis()
        if stop_at is not None and s >= stop_at:
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
