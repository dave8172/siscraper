"""Run: python3 -m tests.test_core   (from the repo root; no network needed)"""
import sys, tempfile, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siscraper.text import to_text
from siscraper.extract import extract, score
from siscraper.memory import Memory
from siscraper.probe import Hit, landed_on_root, probe_host
from siscraper import Session
from siscraper.fetch import RateLimiter, Result

def check(name, got, want):
    assert got == want, f"{name}: got {got!r}, want {want!r}"
    print(f"  ok  {name}")

print("text")
check("strips script", to_text("<p>Earn 30%</p><script>var x=1</script>"), "Earn 30%")
check("dedupes", to_text("<p>same</p><p>same</p>"), "same")
check("entities", to_text("<p>&euro;100 &amp; more</p>"), "€100 & more")
check("empty", to_text(""), "")

print("extract")
t = "Earn 30% commission\nWe use cookies to improve your experience\n60-day cookie window"
e = extract(t, [r"\d+ ?%", "cookie"], noise=[r"we use cookies"])
check("noise subtracted", e.lines, ["Earn 30% commission", "60-day cookie window"])
e2 = extract(t, [r"\d+ ?%", "cookie"], noise=[r"we use cookies"], max_lines=1)
check("caps", len(e2.lines), 1)
check("cap reports truncation", e2.truncated, True)
e3 = extract("30% off\n30% off\n30% off", [r"\d+ ?%"], max_lines=5)
check("dedupe is not truncation", e3.truncated, False)
check("dedupe still counted", (e3.matched, e3.total), (1, 3))
check("score counts", score("affiliate affiliate commission", ["affiliate", "commission"]), 3)
# The spec-table case: only the label matches, the answer is the next line.
table = "Commission Structure\n50%\nCookie window\n90 days\nSupport\nEmail"
check("without after, the answer is lost",
      extract(table, ["cookie", "commission"]).lines,
      ["Commission Structure", "Cookie window"])
check("after=1 keeps the value",
      extract(table, ["cookie", "commission"], after=1).lines,
      ["Commission Structure", "50%", "Cookie window", "90 days"])
check("after does not run past its window",
      "Support" in extract(table, ["cookie", "commission"], after=1).lines, False)
e_t = extract(table, ["cookie", "commission"], after=1)
check("after does not inflate the match count", e_t.matched, 2)
check("but the context lines are still counted as gathered", e_t.collected, 4)
check("nothing was truncated", e_t.truncated, False)
e_cap = extract(table, ["cookie", "commission"], after=1, max_lines=3)
check("truncation is measured against everything gathered", e_cap.truncated, True)

print("memory")
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    (root / "seed").mkdir()
    (root / "seed" / "hosts.seed.json").write_text(json.dumps(
        {"blocked.com": {"reach": "blocked", "reason": "cf", "last_seen": "2026-09-10"}}))
    (root / "seed" / "paths.seed.json").write_text(json.dumps(
        {"t": {"/a": {"tried": 0, "won": 1}, "/b": {"tried": 0, "won": 9}}}))
    m = Memory(root=root)
    check("seed lookup", m.known("blocked.com").skip, True)
    check("unknown host", m.known("nope.com").seen, False)
    check("seed orders by wins", m.path_order("t")[0], "/b")
    m.record_reach("blocked.com", "ok", url="https://blocked.com/x", path="/x")
    check("local overrides seed", m.known("blocked.com").reach, "ok")
    check("local wins source", m.known("blocked.com").source, "local")
    old = Memory(root=root)
    old.hosts["stale.com"] = {"reach": "blocked", "last_seen": "2020-01-01"}
    check("stale block is retried", old.known("stale.com").skip, False)

print("probe")
check("root bounce is a miss", landed_on_root("/affiliates", "https://x.com/"), True)
check("trailing slash root too", landed_on_root("/partners", "https://x.com"), True)
check("helpful redirect still counts",
      landed_on_root("/affiliates", "https://x.com/affiliate-program/"), False)
check("same path is not a bounce",
      landed_on_root("/partners", "https://www.x.com/partners/"), False)
check("asking for root is not a bounce", landed_on_root("/", "https://x.com/"), False)

print("giving up")
class _Refusing:
    """Every path answers 429; nothing is ever readable."""
    def __init__(self): self.calls = 0
    def get(self, url, escalate=False):
        self.calls += 1
        return Result(url=url, final_url=url, status=429, body="Just a moment...")

f = _Refusing()
h = probe_host("strict.com", ["/a", "/b", "/c", "/d", "/e"], ["affiliate"],
               fetcher=f, give_up_after=3)
check("stops after three refusals", f.calls, 3)
check("records what it skipped", h.gave_up, 2)
check("skipped paths are not logged as attempts", len(h.attempts), 3)

class _NotFound:
    def __init__(self): self.calls = 0
    def get(self, url, escalate=False):
        self.calls += 1
        return Result(url=url, final_url=url, status=404, body="<p>nope</p>")

f2 = _NotFound()
probe_host("quiet.com", ["/a", "/b", "/c", "/d", "/e"], ["affiliate"],
           fetcher=f2, give_up_after=3)
check("404s are answers, not refusals — sweep continues", f2.calls, 5)

print("sweep bookkeeping")
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    (root / "seed").mkdir()
    s404 = Session("t", root=root)
    # Every path answered, nothing found: the host is fine, the paths were wrong.
    s404._record_miss(Hit(host="quiet.com", attempts=[
        {"path": "/a", "status": 404, "diagnosis": "not-found", "score": 0},
        {"path": "/b", "status": 404, "diagnosis": "not-found", "score": 0}]))
    check("404 sweep is not a block", s404.memory.known("quiet.com").reach, "ok")
    check("404 sweep is retried later", s404.memory.known("quiet.com").skip, False)
    check("404 sweep is a task outcome",
          s404.memory.known("quiet.com").status, "not-found")
    # Nothing answered at all: that is worth not paying for twice.
    s404._record_miss(Hit(host="walled.com", attempts=[
        {"path": "/a", "status": 0, "diagnosis": "cloudflare-interstitial", "score": 0},
        {"path": "/b", "status": 0, "diagnosis": "timeout", "score": 0}]))
    check("unreachable host is blocked",
          s404.memory.known("walled.com").reach, "blocked")
    check("blocked host is skipped", s404.memory.known("walled.com").skip, True)
    # Throttling says nothing about whether the host has what we want.
    s404._record_miss(Hit(host="strict.com", attempts=[
        {"path": "/a", "status": 429, "diagnosis": "rate-limited", "score": 0},
        {"path": "/b", "status": 429, "diagnosis": "rate-limited", "score": 0}]))
    check("throttled is neither block nor verdict",
          (s404.memory.known("strict.com").reach,
           s404.memory.known("strict.com").status), ("ok", "throttled"))

    # A namespaced task key must not be read as a subdirectory.
    ns = Session("main/sub", root=root)
    f = ns.memory.log_run("main/sub", [Hit(host="h.com", path="/a", attempts=[
        {"path": "/a", "status": 200, "diagnosis": "ok", "score": 9}])])
    check("namespaced task logs to one file", f.parent.name, "runs")
    check("the key itself is preserved in the rows",
          json.loads(f.read_text())["task"], "main/sub")
    check("and namespaces stay out of the main task's rates",
          ns.memory.recompute_paths("main").get("main"), None)

print("fetch diagnosis")
r429 = Result(url="u", status=429, body="Just a moment...")
check("429 outranks the interstitial it ships with", r429.diagnosis(), "rate-limited")
check("empty 200 is not ok", Result(url="u", status=200, body="").diagnosis(), "empty-body")
check("real 200 is ok", Result(url="u", status=200, body="<p>hi</p>").diagnosis(), "ok")
lim = RateLimiter(1.0)
check("penalty compounds", (lim.penalise("h"), lim.penalise("h")), (4.0, 16.0))
check("penalty is capped", lim.penalise("h"), RateLimiter.MAX_INTERVAL)
check("one host's penalty is its own", lim.interval_for("other"), 1.0)

print("\nall passed")
