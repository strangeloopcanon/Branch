"""Utility helpers for *Branch*.

Only pure-Python, dependency-free helpers live here so that higher-level
modules stay concise.
"""

from __future__ import annotations

import re
import unicodedata


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def slugify(text: str, sep: str = "-") -> str:
    """Return a filesystem-safe, ASCII-only slug derived from *text*.

    The implementation purposefully stays *simple*: we normalise the string to
    NFKD, drop non-ASCII characters, replace groups of *unsafe* characters with
    a single *sep* and strip leading/trailing separators.
    """

    # Decompose, drop accents then purge non-ASCII chars.
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()

    # Replace any non-alnum run with *sep*, collapse multiples, then trim.
    text = re.sub(r"[^A-Za-z0-9]+", sep, text)
    text = re.sub(fr"{re.escape(sep)}+", sep, text).strip(sep)

    return text or "untitled"  # guarantee non-empty
