"""Run: python3 -m tests.test_core   (from the repo root; no network needed)"""
import sys, tempfile, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from siscraper.text import to_text
from siscraper.extract import extract, score
from siscraper.memory import Memory

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

print("\nall passed")
