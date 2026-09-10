"""siscraper — a self-improving scraper.

Copyable by design: every consumer gets code plus a small curated seed, then
grows its own local memory. Read order is local first, seed as the floor.
"""
import hashlib
import time
from .extract import Extract, extract, score
from .fetch import Fetcher, RateLimiter, Result
from .memory import Known, Memory
from .probe import Hit, host_of, probe_host, probe_many
from .text import to_text

__all__ = ["Fetcher", "RateLimiter", "Result", "to_text", "extract", "Extract",
           "score", "Memory", "Known", "probe_host", "probe_many", "Hit",
           "host_of", "Session"]
__version__ = "0.1.0"


class Session:
    """The normal entry point: memory-aware probing.

    Checks what is already known before spending a request, orders paths by
    measured win rate, records what happens, and logs every attempt so the
    ordering can be recomputed later.
    """

    def __init__(self, task, root=".", seed_dir=None, fetcher=None,
                 explore=0.1, **fetch_kw):
        self.task = task
        self.memory = Memory(root=root, seed_dir=seed_dir)
        self.fetcher = fetcher or Fetcher(**fetch_kw)
        self.explore = explore

    def known(self, host):
        return self.memory.known(host)

    def sweep(self, hosts, keywords, paths=None, workers=8, **kw):
        """Probe hosts for this task, skipping ones memory says are blocked."""
        order = paths or self.memory.path_order(self.task)
        todo, skipped = [], []
        for h in hosts:
            if self.memory.known(h).skip and not self._explore(h):
                skipped.append(h)
            else:
                todo.append(h)
        hits = probe_many(todo, order, keywords, workers=workers,
                          fetcher=self.fetcher, **kw) if todo else []
        for h in hits:
            if h.found:
                self.memory.record_reach(h.host, "ok", rung="plain",
                                         url=h.url, path=h.path)
            else:
                last = h.attempts[-1]["diagnosis"] if h.attempts else "unknown"
                self.memory.record_reach(h.host, "blocked", reason=last)
        if hits:
            self.memory.log_run(self.task, hits)
        return hits, skipped

    def _explore(self, host: str) -> bool:
        """Deliberately retry a host memory says to skip.

        Without this, a scraper that trusts its own memory can only ever lose
        hosts: every block is permanent until it ages out, and a site that
        starts allowing traffic again is never noticed. The larger and more
        trusted the memory, the worse the effect -- which is why this matters
        far more for pooled memory than for one machine's.

        Deterministic per host and day, so a given host is retried predictably
        rather than at random on every run.
        """
        if self.explore <= 0:
            return False
        seed = f"{host}:{self.task}:{time.strftime('%Y-%m-%d')}"
        digest = hashlib.sha256(seed.encode()).digest()
        return (int.from_bytes(digest[:4], "big") / 0xFFFFFFFF) < self.explore

    def read(self, url, want, protect=(), max_lines=30, escalate=True):
        """Fetch one page and return only the lines that could hold an answer."""
        r = self.fetcher.get(url, escalate=escalate)
        if not r.ok or r.js_shell:
            return None, r
        text = to_text(r.body)
        noise = self.memory.noise_patterns("html")
        return extract(text, want, noise=noise, protect=protect,
                       max_lines=max_lines), r
