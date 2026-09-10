"""siscraper — a self-improving scraper.

Copyable by design: every consumer gets code plus a small curated seed, then
grows its own local memory. Read order is local first, seed as the floor.
"""
import hashlib
import time
from collections import Counter
from .extract import Extract, extract, score
from .fetch import Fetcher, RateLimiter, Result
from .memory import Known, Memory
from .probe import Hit, host_of, probe_host, probe_many
from .text import to_text

__all__ = ["Fetcher", "RateLimiter", "Result", "to_text", "extract", "Extract",
           "score", "Memory", "Known", "probe_host", "probe_many", "Hit",
           "host_of", "Session", "REACHED"]
__version__ = "0.1.1"

# Diagnoses that prove the host answered us.
#
# A 404 is a reachable host with nothing at that path. An interstitial, a
# timeout or a DNS failure is a host we could not reach at all. Writing
# "blocked" over the first kind is not a cosmetic error: `Known.skip` then
# refuses to spend a request on that host for ninety days, so a site whose
# programme simply sits at a path nobody guessed becomes permanently
# invisible -- and it looks like memory working, not memory lying.
#
# Reachability is universal and ships in the seed; "nothing at the paths I
# swept" is one task's finding and stays local (seed/RULES.md §13, §14).
REACHED = frozenset({"ok", "not-found", "js-shell", "redirected-to-root",
                     "empty-body", "rate-limited"})

# A host that only ever answered 429 has not told us anything about whether
# it has what we want. Recording that as "not-found" would be inventing a
# verdict; recording it as a block would refuse to ask again for ninety days
# over what is a temporary state of our own making.
THROTTLED = "rate-limited"


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
                self._record_miss(h)
        if hits:
            self.memory.log_run(self.task, hits)
        return hits, skipped

    def _record_miss(self, hit):
        """A sweep that found nothing is two different facts, not one.

        Every path 404ing means the host is fine and the paths were wrong --
        a task outcome, retried the moment the path list grows. Every path
        timing out means the host is unreachable, which is worth not paying
        for twice. Only the second is a block.
        """
        seen = [a["diagnosis"] for a in hit.attempts]
        dominant = Counter(seen).most_common(1)[0][0] if seen else "unknown"
        if set(seen) & REACHED:
            self.memory.record_reach(hit.host, "ok", rung="plain")
            status = "throttled" if dominant == THROTTLED else "not-found"
            self.memory.record_outcome(
                hit.host, self.task, status, reason=dominant)
        else:
            self.memory.record_reach(hit.host, "blocked", reason=dominant)

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

    def read(self, url, want, protect=(), max_lines=30, escalate=True, after=1):
        """Fetch one page and return only the lines that could hold an answer.

        `after` defaults to 1 because spec tables are everywhere: the label
        matches the want-list and the value sits on the next line, so reading
        line-at-a-time returns "Cookie window" and discards "90 days".
        """
        r = self.fetcher.get(url, escalate=escalate)
        if not r.ok or r.js_shell:
            return None, r
        text = to_text(r.body)
        noise = self.memory.noise_patterns("html")
        return extract(text, want, noise=noise, protect=protect,
                       max_lines=max_lines, after=after), r
