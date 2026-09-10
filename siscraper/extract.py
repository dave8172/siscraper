"""Pull the interesting lines out of a page, and nothing else.

The scarce resource is not requests, it is the tokens spent reading what comes
back. Everything here exists to hand a caller the smallest set of lines that
could contain the answer: match on what you want, subtract known boilerplate,
deduplicate, and cap hard.
"""
import re
from dataclasses import dataclass

DEFAULT_MAX_LINES = 30
DEFAULT_MAX_CHARS = 190


@dataclass
class Extract:
    lines: list[str]
    matched: int          # distinct lines that matched, before the cap
    total: int = 0        # every match including duplicates

    @property
    def truncated(self) -> bool:
        """True only when the cap dropped something.

        Kept distinct from deduplication on purpose: a caller that sees
        `truncated` needs to know whether raising max_lines would reveal more,
        and removing a repeated line does not mean anything was lost.
        """
        return self.matched > len(self.lines)

    def __str__(self) -> str:
        return "\n".join(self.lines)


def extract(text: str, want, noise=(), protect=(), max_lines: int = DEFAULT_MAX_LINES,
            max_chars: int = DEFAULT_MAX_CHARS) -> Extract:
    """`want` and `noise` are regex strings or compiled patterns.

    Noise is subtracted after matching, never before: the boilerplate that
    pollutes a search usually contains the very word being searched for.
    Cookie-consent banners are the canonical case -- searching a page for
    "cookie" without subtracting them buries the one line that matters.

    `protect` is the other half of that, and it is not optional in practice.
    A noise list tuned to kill consent banners will eventually kill a real
    sentence containing the same words -- one vendor answers "What is your
    referral cookie policy?" with the actual window, and a pattern matching
    "cookie policy" deletes the answer. A line matching `protect` survives
    noise: it should only remove lines that are *nothing but* boilerplate.
    """
    want_re = _compile(want)
    noise_re = _compile(noise) if noise else None
    protect_re = _compile(protect) if protect else None

    seen, distinct, total = set(), [], 0
    for raw in text.split("\n"):
        line = raw.strip()
        if not line or not want_re.search(line):
            continue
        if noise_re and noise_re.search(line):
            if not (protect_re and protect_re.search(line)):
                continue
        total += 1
        clipped = line[:max_chars]
        if clipped in seen:
            continue
        seen.add(clipped)
        distinct.append(clipped)
    return Extract(lines=distinct[:max_lines], matched=len(distinct), total=total)


def score(text: str, keywords, weights=None) -> int:
    """Cheap relevance signal, used to decide whether a page is worth reading.

    A 200 means nothing -- plenty of sites serve a catch-all page for any
    unknown path. Counting the words that would have to appear on a real one
    is what separates them, and it costs no extra request.
    """
    low = text.lower()
    weights = weights or {}
    total = 0
    for kw in keywords:
        hits = low.count(kw.lower())
        total += hits * weights.get(kw, 1)
    return total


def _compile(patterns):
    if hasattr(patterns, "search"):
        return patterns
    if isinstance(patterns, str):
        return re.compile(patterns, re.I)
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)
