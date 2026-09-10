"""HTML -> readable text.

Deliberately not a parser. The job is to get from markup to lines a keyword
search can work on, losing anything that would produce false hits: script and
style bodies, SVG paths, comments. Two unrelated scripts each hand-rolled a
worse version of this before it lived here.
"""
import re

_DROP = re.compile(
    r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1>", re.I | re.S)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BLOCK_END = re.compile(
    r"</(p|div|li|tr|h[1-6]|section|article|td|th|dt|dd|figcaption)>", re.I)
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")

_ENTITIES = {
    "&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&quot;": '"', "&ldquo;": '"', "&rdquo;": '"',
    "&#x27;": "'", "&#39;": "'", "&rsquo;": "'", "&lsquo;": "'",
    "&mdash;": "—", "&ndash;": "–", "&hellip;": "…",
    "&euro;": "€", "&pound;": "£",
}
_NUMERIC = re.compile(r"&#(\d+);")
_LEFTOVER = re.compile(r"&[a-zA-Z]+;")


def to_text(html: str) -> str:
    """Reduce a page to deduplicated, whitespace-collapsed lines."""
    if not html:
        return ""
    s = _DROP.sub(" ", html)
    s = _COMMENT.sub(" ", s)
    s = _BLOCK_END.sub("\n", s)
    s = _BR.sub("\n", s)
    s = _TAG.sub(" ", s)

    for ent, char in _ENTITIES.items():
        s = s.replace(ent, char)
    s = _NUMERIC.sub(lambda m: _safe_chr(m.group(1)), s)
    s = _LEFTOVER.sub(" ", s)

    out, prev = [], None
    for raw in s.split("\n"):
        line = " ".join(raw.split())
        # Single characters are almost always layout debris, not content.
        if len(line) > 1 and line != prev:
            out.append(line)
            prev = line
    return "\n".join(out)


def _safe_chr(code: str) -> str:
    try:
        return chr(int(code))
    except (ValueError, OverflowError):
        return " "
