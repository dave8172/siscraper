"""Seed + local memory. This is the part that makes the scraper self-improving.

Three kinds of knowledge, separated by who writes them and whether they can be
recomputed. Collapsing them is what makes scraper knowledge rot:

  reachability  can this host be fetched at all, and at which rung. Written by
                the tool. UNIVERSAL -- true regardless of what you wanted from
                the host -- so it is the only host knowledge that ships in the
                seed. Rare, because most hosts are simply reachable, which is
                why the shared part stays small forever.

  outcomes      what a host yielded for one task ("no affiliate programme").
                Written by the tool. LOCAL to the project, because it is only
                meaningful inside that task.

  paths         which URL paths pay off, per task. NEVER hand-written --
                always recomputed from the run log, so you can always tell
                measurement from guesswork.

Prose rules -- the things counting can never discover -- live in seed/RULES.md
and are read by humans and agents, not by this module.

Read order is local first, seed as the floor. Nobody starts at zero, and
nobody inherits another project's context.
"""
import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SEED_DIRNAME = "seed"
LOCAL_DIRNAME = "memory"

# How long a reachability verdict is trusted before it is worth retrying.
# A block from eight months ago says little; yesterday's says plenty.
STALE_DAYS = 90


@dataclass
class Known:
    """What memory can say about a host before a single request is spent."""
    host: str
    seen: bool = False
    reach: str = ""          # "ok" | "blocked" | "" (unknown)
    reason: str = ""
    rung: str = ""           # deepest rung already attempted
    url: str = ""            # the page that worked, if one did
    path: str = ""
    status: str = ""         # task outcome, e.g. "none" | "ok"
    last_seen: str = ""
    stale: bool = False
    source: str = ""         # "local" | "seed"

    @property
    def skip(self) -> bool:
        """True when spending a request would just re-buy a known answer."""
        return self.seen and self.reach == "blocked" and not self.stale


class Memory:
    def __init__(self, root=".", seed_dir=None):
        self.root = Path(root)
        self.seed_dir = Path(seed_dir) if seed_dir else self.root / SEED_DIRNAME
        self.local_dir = self.root / LOCAL_DIRNAME
        self._lock = threading.Lock()
        self.seed_hosts = _load(self.seed_dir / "hosts.seed.json")
        self.seed_paths = _load(self.seed_dir / "paths.seed.json")
        self.noise = _load(self.seed_dir / "noise.json")
        self.hosts = _load(self.local_dir / "hosts.json")
        self.paths = _load(self.local_dir / "paths.json")

    # -- reading -----------------------------------------------------------
    def known(self, host: str) -> Known:
        host = host.lower()
        local, seed = self.hosts.get(host), self.seed_hosts.get(host)
        rec = local or seed
        if not rec:
            return Known(host=host)
        k = Known(host=host, seen=True, source="local" if local else "seed",
                  reach=rec.get("reach", ""), reason=rec.get("reason", ""),
                  rung=rec.get("rung", ""), url=rec.get("url", ""),
                  path=rec.get("path", ""), status=rec.get("status", ""),
                  last_seen=rec.get("last_seen", ""))
        k.stale = _is_stale(k.last_seen)
        # A seed block is a floor, not a verdict: if local ever succeeded, the
        # local record wins outright, which the read order already handles.
        return k

    def path_order(self, task: str, fallback=()) -> list:
        """Paths ordered by measured win rate, richest first.

        Local measurements outrank the seed's starting guesses. Paths never
        tried locally keep their seed order behind the measured ones, so a
        thin local history degrades gracefully instead of discarding options.
        """
        measured = self.paths.get(task, {})
        seeded = self.seed_paths.get(task, {})
        candidates = list(dict.fromkeys(
            list(measured) + list(seeded) + list(fallback)))

        def rank(p):
            m = measured.get(p)
            if m and m.get("tried"):
                return (0, -(m["won"] / m["tried"]), -m["won"])
            s = seeded.get(p)
            if s and s.get("tried"):
                return (1, -(s["won"] / s["tried"]), -s["won"])
            if s:
                return (1, 0, -s.get("won", 0))
            return (2, 0, 0)

        return sorted(candidates, key=rank)

    def noise_patterns(self, name="html") -> list:
        return self.noise.get(name, [])

    # -- writing -----------------------------------------------------------
    def record_reach(self, host, reach, reason="", rung="", url="", path=""):
        with self._lock:
            rec = self.hosts.setdefault(host.lower(), {})
            rec.update({"reach": reach, "reason": reason, "rung": rung,
                        "last_seen": _today()})
            if url:
                rec["url"], rec["path"] = url, path
            _dump(self.local_dir / "hosts.json", self.hosts)

    def record_outcome(self, host, task, status, reason="", evidence=""):
        """A task-level finding. Never promoted to the seed automatically --
        'this host has no affiliate programme' is one project's finding, not a
        universal fact."""
        with self._lock:
            rec = self.hosts.setdefault(host.lower(), {})
            rec.setdefault("tasks", {})[task] = {
                "status": status, "reason": reason,
                "evidence": evidence, "last_seen": _today()}
            rec["status"] = status
            rec["last_seen"] = _today()
            _dump(self.local_dir / "hosts.json", self.hosts)

    def log_run(self, task, hits) -> Path:
        """Append every attempt, not just the winner.

        Recording only the winning path makes win counts computable and hit
        *rates* impossible -- the denominator is gone. That is not a footnote:
        it cannot be backfilled, and it is the whole input to path tuning.
        """
        runs = self.local_dir / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        # A task key may be namespaced ("affiliate-terms/escalated"), which is
        # a legitimate way to keep a biased sub-run out of the main task's
        # denominators. The key goes in the rows; only the filename needs
        # flattening, and a slash there silently means "subdirectory".
        f = runs / f"{_safe(task)}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        with open(f, "w", encoding="utf-8") as fh:
            for h in hits:
                fh.write(json.dumps({
                    "host": h.host, "task": task, "won_path": h.path,
                    "score": h.score, "gave_up": getattr(h, "gave_up", 0),
                    "attempts": h.attempts,
                }, ensure_ascii=False) + "\n")
        return f

    def recompute_paths(self, task=None) -> dict:
        """Rebuild paths.json from the run log. Derived, never edited -- the
        moment someone types a number in here you can no longer tell which
        parts are measured."""
        runs = self.local_dir / "runs"
        counts = defaultdict(lambda: defaultdict(lambda: {"tried": 0, "won": 0}))
        for f in sorted(runs.glob("*.jsonl")) if runs.exists() else []:
            for line in open(f, encoding="utf-8"):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = row.get("task") or "default"
                if task and t != task:
                    continue
                for a in row.get("attempts", []):
                    counts[t][a["path"]]["tried"] += 1
                if row.get("won_path"):
                    counts[t][row["won_path"]]["won"] += 1
        merged = {t: {p: dict(v) for p, v in paths.items()}
                  for t, paths in counts.items()}
        with self._lock:
            self.paths.update(merged)
            _dump(self.local_dir / "paths.json", self.paths)
        return merged


def _load(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _dump(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False,
                              sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _safe(name: str) -> str:
    """A task key reduced to something that is only ever a filename."""
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in name)


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _is_stale(last_seen: str, days: int = STALE_DAYS) -> bool:
    if not last_seen:
        return True
    try:
        seen = time.mktime(time.strptime(last_seen, "%Y-%m-%d"))
    except ValueError:
        return True
    return (time.time() - seen) > days * 86400
