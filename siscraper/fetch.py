"""Fetching, with an escalation ladder that names which rung failed.

The point of the ladder is not persistence, it is diagnosis. "Blocked by a
Cloudflare interstitial even under a real browser" and "404" and "the HTML
parsed but the answer is rendered by script" are three different facts, and a
scraper that collapses them into "failed" makes the same expensive mistake
every run.
"""
import glob
import http.cookiejar
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

# Rungs, cheapest first. `reach` values in memory use these names.
PLAIN, HEADLESS = "plain", "headless"

_INTERSTITIAL = re.compile(
    r"just a moment|checking your browser|enable javascript and cookies|"
    r"performing security verification|cf-browser-verification|challenge-platform",
    re.I)

# A page that is only a script shell: almost no text, but real markup.
_SHELL_TEXT_FLOOR = 400


@dataclass
class Result:
    url: str
    final_url: str = ""
    status: int = 0
    body: str = ""
    rung: str = PLAIN
    error: str = ""          # "" when the fetch itself worked
    interstitial: bool = False
    js_shell: bool = False
    retry_after: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error and not self.interstitial

    def diagnosis(self) -> str:
        """One token describing the outcome, for the host memory."""
        # 429 first, and ahead of the interstitial test on purpose: Cloudflare
        # serves its challenge page *with* a 429 when it is throttling rather
        # than challenging. Both look identical in the body and mean opposite
        # things -- an interstitial never clears, a throttle clears by waiting.
        if self.status == 429:
            return "rate-limited"
        if self.interstitial:
            return "cloudflare-interstitial"
        if self.error:
            return self.error
        if self.status == 404:
            return "not-found"
        # A 200 that carried no document at all. Not an error, not a shell,
        # and emphatically not "ok" -- a browser would render nothing either,
        # so escalating buys nothing and the honest answer is that the page
        # is empty. jotform.com/partner/ serves a 20-byte empty gzip stream.
        if self.status == 200 and not self.body.strip():
            return "empty-body"
        if self.status in (401, 403):
            return "forbidden"
        if self.status >= 500:
            return "server-error"
        # A 3xx that survived the redirect handler is a loop, not a move.
        if 300 <= self.status < 400:
            return "redirect-loop"
        if self.js_shell:
            return "js-shell"
        if self.status == 200:
            return "ok"
        return f"http-{self.status}"


class RateLimiter:
    """Per-host minimum interval. Global parallelism is not politeness --
    fourteen workers spread over eighty domains is fine, fourteen aimed at one
    host is not."""

    MAX_INTERVAL = 30.0

    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self._last: dict[str, float] = {}
        self._interval: dict[str, float] = {}
        self._lock = threading.Lock()

    def interval_for(self, host: str) -> float:
        return self._interval.get(host, self.min_interval)

    def penalise(self, host: str, factor: float = 4.0) -> float:
        """A 429 is the host telling you your rate is wrong. Believe it.

        Retrying at the same pace is what turns one throttled host into a
        whole sweep of them, and the cost lands on the next task to touch
        that host as much as on this one. The slower interval sticks for the
        rest of the run rather than for one request.
        """
        with self._lock:
            cur = self._interval.get(host, self.min_interval) or 1.0
            self._interval[host] = min(cur * factor, self.MAX_INTERVAL)
            return self._interval[host]

    def wait(self, host: str) -> None:
        if self.min_interval <= 0 and host not in self._interval:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                gap = self._interval.get(host, self.min_interval)
                earliest = self._last.get(host, 0.0) + gap
                if now >= earliest:
                    self._last[host] = now
                    return
                delay = earliest - now
            time.sleep(delay)


@dataclass
class Fetcher:
    timeout: int = 25
    min_interval: float = 1.0
    respect_robots: bool = True
    limiter: RateLimiter = field(default=None)
    opener: object = field(default=None)
    _robots: dict = field(default_factory=dict)
    _robots_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        if self.limiter is None:
            self.limiter = RateLimiter(self.min_interval)
        # A cookie jar, because a surprising number of sites 301 to *the same
        # URL* after setting a cookie -- a language or region gate. Without a
        # jar that is an infinite redirect the stdlib aborts as "http-301",
        # which looks like a broken link and is actually a page that works
        # fine in any browser. snov.io/affiliate-program does exactly this.
        if self.opener is None:
            self.opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    # -- rung 1 ------------------------------------------------------------
    def plain(self, url: str) -> Result:
        r = Result(url=url, rung=PLAIN)
        host = urlparse(url).hostname or ""
        if self.respect_robots and not self._allowed(url, host):
            r.error = "robots-disallowed"
            return r
        self.limiter.wait(host)
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
                r.status = resp.status
                r.final_url = resp.geturl()
                r.body = _decode(raw, resp.headers)
        except urllib.error.HTTPError as e:
            r.status = e.code
            r.final_url = url
            r.retry_after = e.headers.get("Retry-After", "") or ""
            try:
                r.body = _decode(e.read(), e.headers)
            except Exception:
                pass
        except Exception as e:                       # timeouts, DNS, TLS, parse
            r.error = _short_error(e)
            return r
        _classify(r)
        return r

    # -- rung 2 ------------------------------------------------------------
    def headless(self, url: str) -> Result:
        """Real browser via chrome-headless-shell --dump-dom. Slow; only worth
        it when rung 1 says js-shell or interstitial."""
        r = Result(url=url, final_url=url, rung=HEADLESS)
        binary = chrome_binary()
        if not binary:
            r.error = "no-headless-binary"
            return r
        self.limiter.wait(urlparse(url).hostname or "")
        try:
            proc = subprocess.run(
                [binary, "--no-sandbox", "--disable-gpu", "--dump-dom",
                 f"--user-agent={UA}", "--virtual-time-budget=8000", url],
                capture_output=True, timeout=self.timeout + 40)
            r.body = proc.stdout.decode("utf-8", "replace")
            r.status = 200 if r.body.strip() else 0
            if not r.body.strip():
                r.error = "headless-empty"
        except subprocess.TimeoutExpired:
            r.error = "headless-timeout"
            return r
        except Exception as e:
            r.error = _short_error(e)
            return r
        _classify(r)
        return r

    # -- the ladder --------------------------------------------------------
    def get(self, url: str, escalate: bool = True) -> Result:
        r = self.plain(url)
        if r.status == 429:
            r = self._after_backoff(url, r)
        elif 300 <= r.status < 400:
            # A cookie gate, not a move: the site redirects to the same URL
            # after setting a cookie, and may need more than one round trip to
            # set all of them. The jar has warmed up by now, so one retry
            # usually lands -- snov.io needs two cookies and succeeds on the
            # second call. Exactly one retry; a real loop stays a loop.
            r = self.plain(url)
        # A js-shell is a *successful* fetch -- 200, no error -- which is
        # exactly why `ok` alone must not end the ladder. The request worked;
        # the page just isn't there yet.
        if not escalate or (r.ok and not r.js_shell):
            return r
        if r.interstitial or r.js_shell:
            up = self.headless(url)
            # Keep whichever rung actually got content.
            if up.ok or (up.body and not r.body):
                return up
            up.rung = HEADLESS
            return up
        return r

    def _after_backoff(self, url: str, first: Result) -> Result:
        """Wait out one throttle and try again; keep the better answer.

        Exactly one retry. A host that is still refusing after honouring its
        own Retry-After is not going to yield to persistence, and the run has
        hundreds of other hosts to spend the time on.
        """
        host = urlparse(url).hostname or ""
        gap = self.limiter.penalise(host)
        wait = _retry_after(first) or gap
        time.sleep(min(wait, RateLimiter.MAX_INTERVAL))
        second = self.plain(url)
        return second if second.status != 429 else first

    def _allowed(self, url: str, host: str) -> bool:
        with self._robots_lock:
            rp = self._robots.get(host)
        if rp is None:
            rp = self._read_robots(url, host)
            with self._robots_lock:
                self._robots[host] = rp
        try:
            return rp.can_fetch(UA, url)
        except Exception:
            return True


    def _read_robots(self, url: str, host: str):
        """Fetch robots.txt ourselves rather than letting RobotFileParser do it.

        Its read() sends Python's default User-Agent, which a lot of sites 403
        -- and a 403 on robots.txt makes it set disallow_all, so the stdlib
        default silently refuses to fetch anything. The same file returns 200
        under a browser UA. An unreadable robots.txt is not a ban.
        """
        scheme = urlparse(url).scheme or "https"
        req = urllib.request.Request(f"{scheme}://{host}/robots.txt",
                                     headers=HEADERS)
        try:
            self.limiter.wait(host)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status != 200:
                    return _AllowAll()
                body = _decode(resp.read(), resp.headers)
        except Exception:
            return _AllowAll()
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(body.splitlines())
        except Exception:
            return _AllowAll()
        return rp


class _AllowAll:
    def can_fetch(self, *_):
        return True


# Where a headless Chrome may be found. SISCRAPER_CHROME overrides all of it.
CHROME_CANDIDATES = (
    "~/.cache/puppeteer/chrome-headless-shell/*/*/chrome-headless-shell",
    "~/.cache/puppeteer/chrome/*/*/chrome",
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def chrome_binary() -> str | None:
    """Find a browser for the second rung, or None -- which is not an error.

    Everything except escalation works without one; a missing browser simply
    means a script-rendered page is reported as such instead of being read.
    """
    override = os.environ.get("SISCRAPER_CHROME")
    if override:
        return override if os.path.exists(override) else None
    for pattern in CHROME_CANDIDATES:
        for hit in sorted(glob.glob(os.path.expanduser(pattern))):
            if os.access(hit, os.X_OK):
                return hit
    return None


def _retry_after(r: Result) -> float:
    """Seconds the host asked for, when it bothered to say."""
    try:
        return float(r.retry_after)
    except (TypeError, ValueError):
        return 0.0


def _decode(raw: bytes, headers) -> str:
    enc = (headers.get("Content-Encoding") or "").lower()
    if enc == "gzip":
        import gzip
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    elif enc == "deflate":
        import zlib
        try:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        except Exception:
            pass
    charset = None
    ct = headers.get("Content-Type") or ""
    if "charset=" in ct:
        charset = ct.split("charset=")[-1].split(";")[0].strip()
    return raw.decode(charset or "utf-8", "replace")


def _classify(r: Result) -> None:
    from .text import to_text
    head = r.body[:6000]
    if _INTERSTITIAL.search(head):
        r.interstitial = True
        return
    if r.status == 200 and len(r.body) > 500:
        if len(to_text(r.body)) < _SHELL_TEXT_FLOOR:
            r.js_shell = True


def _short_error(e: Exception) -> str:
    name = type(e).__name__
    msg = str(e)[:80]
    if "timed out" in msg.lower() or name == "timeout":
        return "timeout"
    if "header" in msg.lower() and "line" in msg.lower():
        return "header-parse-error"     # Webflow does this
    return f"{name}: {msg}" if msg else name
