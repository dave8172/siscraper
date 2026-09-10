"""Command line. `python3 -m siscraper <command>`

  init <target>     vendor code + seed into another project as .siscraper/
  known <host>      what memory already knows, before spending a request
  fetch <url>       fetch one page, report which rung and what diagnosis
  read <url>        fetch and print only the lines that could hold an answer
  probe <host…>     sweep paths across hosts for a task
  recompute         rebuild paths.json from the run log
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

from . import Session, __version__
from .fetch import Fetcher
from .memory import Memory
from .text import to_text

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def cmd_init(args):
    """Vendor a working copy into another project.

    Deliberately a copy, not a package dependency or a submodule. It installs
    with no network, no version resolution and no build step -- and a project
    that gets handed to someone else carries a self-contained tool rather than
    a reference to a repo they cannot reach.
    """
    target = Path(args.target).resolve() / ".siscraper"
    if target.exists() and not args.force:
        print(f"{target} exists — pass --force to overwrite code and seed")
        return 1
    (target / "memory" / "runs").mkdir(parents=True, exist_ok=True)
    shutil.copytree(HERE, target / "siscraper", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(REPO / "seed", target / "seed", dirs_exist_ok=True)
    (target / "README.md").write_text(
        f"# siscraper {__version__} (vendored)\n\n"
        "`seed/` is read-only — refresh it by re-running `init --force`.\n"
        "`memory/` is this project's own and grows as it runs. Local memory\n"
        "wins over seed; the seed is a floor, not a ceiling.\n\n"
        "    import sys; sys.path.insert(0, '.siscraper')\n"
        "    from siscraper import Session\n"
        "    s = Session('my-task', root='.siscraper')\n\n"
        "Read `seed/RULES.md` before interpreting anything it returns.\n",
        encoding="utf-8")
    print(f"vendored siscraper {__version__} -> {target}")
    print("  seed/    read-only, refresh with init --force")
    print("  memory/  local, grows as it runs")
    return 0


def cmd_known(args):
    k = Memory(root=args.root).known(args.host)
    print(json.dumps(k.__dict__ | {"skip": k.skip}, indent=2))
    return 0


def cmd_fetch(args):
    r = Fetcher(min_interval=args.interval).get(args.url, escalate=not args.no_escalate)
    print(f"{r.status} {r.diagnosis()}  rung={r.rung}  bytes={len(r.body)}")
    if r.final_url and r.final_url != r.url:
        print(f"-> {r.final_url}")
    return 0 if r.ok else 1


def cmd_read(args):
    s = Session(args.task, root=args.root, min_interval=args.interval)
    ex, r = s.read(args.url, args.want.split(","), max_lines=args.lines)
    if ex is None:
        print(f"{r.status} {r.diagnosis()}", file=sys.stderr)
        return 1
    print(f"# {r.final_url}  ({ex.matched} matched, {len(ex.lines)} shown"
          f"{', truncated' if ex.truncated else ''})")
    print(ex)
    return 0


def cmd_probe(args):
    s = Session(args.task, root=args.root, min_interval=args.interval)
    hosts = args.hosts or [h.strip() for h in sys.stdin if h.strip()]
    hits, skipped = s.sweep(hosts, args.keywords.split(","),
                            workers=args.workers,
                            stop_at=args.stop_at, escalate=args.escalate)
    for h in sorted(hits, key=lambda x: -x.score):
        print(f"{h.score:6}  {h.host:28}  {h.url or '-'}")
    if skipped:
        print(f"\nskipped {len(skipped)} known-blocked: {', '.join(skipped)}",
              file=sys.stderr)
    s.memory.recompute_paths(args.task)
    return 0


def cmd_recompute(args):
    out = Memory(root=args.root).recompute_paths(args.task)
    for task, paths in out.items():
        print(task)
        for p, v in sorted(paths.items(), key=lambda kv: -kv[1]["won"]):
            rate = f"{v['won'] / v['tried']:.0%}" if v["tried"] else "  -"
            print(f"  {rate:>5}  {v['won']:4}/{v['tried']:<4}  {p}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="siscraper", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".", help="memory root (default: .)")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="per-host minimum seconds between requests")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init"); p.add_argument("target"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_init)
    p = sub.add_parser("known"); p.add_argument("host"); p.set_defaults(fn=cmd_known)
    p = sub.add_parser("fetch"); p.add_argument("url"); p.add_argument("--no-escalate", action="store_true"); p.set_defaults(fn=cmd_fetch)
    p = sub.add_parser("read"); p.add_argument("url"); p.add_argument("--task", default="default")
    p.add_argument("--want", default=r"\d+ ?%,commission,cookie,payout,minimum")
    p.add_argument("--lines", type=int, default=30); p.set_defaults(fn=cmd_read)
    p = sub.add_parser("probe"); p.add_argument("hosts", nargs="*"); p.add_argument("--task", default="default")
    p.add_argument("--keywords", default="affiliate,commission,cookie,payout")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--stop-at", type=int, default=None)
    p.add_argument("--escalate", action="store_true"); p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("recompute"); p.add_argument("--task", default=None); p.set_defaults(fn=cmd_recompute)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
