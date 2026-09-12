"""Run: python3 -m tests.test_scoping   (from the repo root; no network needed)

The scoping gate. siscraper knows about scraping and nothing else, and the
part of it that every clone inherits must be true regardless of what the
cloner is looking for.

This exists because the rule was written down and then broken anyway, in four
places at once: seed/paths.seed.json shipped one project's measured path
rates, the README republished them in prose, RULES.md named which paths won,
and the CLI defaulted --want and --keywords to that project's task. Each was a
reasonable decision on its own — a measured order beats a guessed one, a
README should show evidence, a default is friendlier than an error.

So the judgement cannot be trusted to hold, and what a machine can check, a
machine checks. What it cannot check is prose: RULES.md explains general
failure modes using concrete examples, and a concrete example needs a real
domain. That is allowed and is not gated here. The line is **functional vs
illustrative** — anything the tool reads, and anything it does by default,
must be domain-free.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures = []


def check(name, got, want):
    if got != want:
        failures.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok  {name}")


# The vocabulary of the first consumer. Not a general solution — you cannot
# enumerate every future task — but the recurrence this gate exists to stop is
# *this* project leaking into the tool, and that is exactly what it catches.
CONSUMER_TERMS = re.compile(
    r"affiliate|commission|payout|cookie[ _-]?window|partnerstack|shareasale|"
    r"tapfiliate|rewardful|firstpromoter|refersion|impact\.com",
    re.I,
)

print("seed carries nothing contextual")

# Path rates are, by this repository's own architecture, local and never
# shipped back. There is no "mostly empty" version of that rule.
paths = json.loads((ROOT / "seed" / "paths.seed.json").read_text())
check("paths.seed.json is empty", paths, {})

# Reachability is universal; a task outcome is not. Allowing only the
# reachability keys blocks the latter without having to name it.
REACH_KEYS = {"reach", "reason", "rung", "last_seen", "checked", "note"}
hosts = json.loads((ROOT / "seed" / "hosts.seed.json").read_text())
stray = sorted({k for rec in hosts.values() for k in rec} - REACH_KEYS)
check("hosts.seed.json holds reachability only", stray, [])
check("no host record carries task outcomes",
      [h for h, r in hosts.items() if "outcomes" in r or "tasks" in r], [])

for name in ("paths.seed.json", "hosts.seed.json", "noise.json"):
    text = (ROOT / "seed" / name).read_text()
    hits = sorted(set(m.group(0).lower() for m in CONSUMER_TERMS.finditer(text)))
    # Hostnames in a reachability record are the fact itself — "impact.com
    # blocks a plain fetch" is true for anyone who hits impact.com.
    if name == "hosts.seed.json":
        hits = [h for h in hits if h not in {"impact.com", "partnerstack"}]
    check(f"{name} carries no task vocabulary", hits, [])

print("\nthe tool does nothing task-shaped by default")

cli = (ROOT / "siscraper" / "cli.py").read_text()
# A default is what someone gets without asking for it. A task-shaped default
# makes a general tool one consumer's tool for everybody who does not read the
# flags.
for flag in ("--want", "--keywords"):
    pattern = re.compile(re.escape(flag) + r"\"[^)]*?default=", re.S)
    check(f"{flag} has no default", bool(pattern.search(cli)), False)

defaults = re.findall(r"default=\"([^\"]*)\"", cli) + re.findall(r"default=r\"([^\"]*)\"", cli)
tainted = sorted({d for d in defaults if CONSUMER_TERMS.search(d)})
check("no argparse default carries task vocabulary", tainted, [])

print("\nthe library is domain-free where it executes")

# Comments may carry an example; a string literal the code acts on may not.
for py in sorted((ROOT / "siscraper").glob("*.py")):
    src = py.read_text()
    stripped = "\n".join(
        re.sub(r"#.*$", "", line) for line in src.split("\n")
    )
    stripped = re.sub(r'"""[\s\S]*?"""', "", stripped)
    stripped = re.sub(r"'''[\s\S]*?'''", "", stripped)
    hits = sorted(set(m.group(0).lower() for m in CONSUMER_TERMS.finditer(stripped)))
    check(f"{py.name} has no task vocabulary outside comments", hits, [])

if failures:
    print(f"\n{len(failures)} scoping failure(s)")
    print("See CONTRIBUTING.md — 'What may enter seed/'. The test for anything")
    print("proposed: would this still be true for someone scraping a completely")
    print("different kind of page?")
    sys.exit(1)

print("\nall passed")
