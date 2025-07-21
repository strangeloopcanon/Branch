"""Synchronise exported Google-Doc HTML into a local Git repo.

Only two call-sites are expected:
• normalise_html() – strip base-64 images → blobs/sha256 files.
• BranchRepo  – add/commit a cleaned *doc.html* idempotently.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

from git import Repo, Actor, GitCommandError

from .utils import slugify


# Pattern solely matching *inside* the attribute value so that we can safely
# run a simple ``re.sub`` without having to reconstruct the whole ``<img>``
# element.

_DATA_URI_RE = re.compile(
    r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)",
    re.IGNORECASE,
)


def normalise_html(html: str, blobs_dir: os.PathLike[str] | str) -> Tuple[str, list[Path]]:
    """Return a tuple ``(clean_html, written_paths)``.

    *clean_html* is the original *html* with embedded base64 images replaced by
    relative links into *blobs_dir* (e.g. ``blobs/<sha256>``).

    *written_paths* lists any new blob files that were created.  Existing blobs
    are **not** duplicated.
    """

    blobs_dir_path = Path(blobs_dir)
    blobs_dir_path.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    def _replace(match: re.Match[str]) -> str:  # noqa: D401 – inner helper
        b64_payload = match.group(1)

        try:
            raw = base64.b64decode(b64_payload)
        except base64.binascii.Error:
            return match.group(0)  # Unable to decode – leave untouched.

        digest = hashlib.sha256(raw).hexdigest()
        blob_path = blobs_dir_path / digest

        if not blob_path.exists():
            blob_path.write_bytes(raw)
            written.append(blob_path)

        return f"blobs/{digest}"

    cleaned = _DATA_URI_RE.sub(_replace, html)

    return cleaned, written


# ---------------------------------------------------------------------------
# Git repository wrapper
# ---------------------------------------------------------------------------


class BranchRepo:
    """A thin wrapper around *GitPython* that manages Branch commits."""

    def __init__(self, root: os.PathLike[str] | str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

        try:
            self.repo = Repo(self.root)
        except (GitCommandError, Exception):
            # Either path not a repo or other issue – initialise a new one.
            self.repo = Repo.init(self.root)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def commit_revision(
        self,
        *,
        doc_title: str,
        html: str,
        author_email: str,
        timestamp: int | float | datetime,
    ) -> str:
        """Write *html* to disk (plus blobs) and commit if there are changes.

        Returns the new commit SHA, or the SHA of the **existing** head commit
        if the contents did **not** change.  This behaviour lets callers remain
        idempotent: running the importer twice for the same revision will *not*
        create duplicate commits.
        """

        # 1. Compute paths
        slug = slugify(doc_title)
        doc_dir = self.root / slug
        blobs_dir = doc_dir / "blobs"
        doc_dir.mkdir(parents=True, exist_ok=True)

        # 2. Clean HTML and write blob files
        cleaned_html, _ = normalise_html(html, blobs_dir)

        doc_path = doc_dir / "doc.html"

        # Skip filesystem write if content unchanged (optimisation).
        if not doc_path.exists() or doc_path.read_text(encoding="utf-8") != cleaned_html:
            doc_path.write_text(cleaned_html, encoding="utf-8")

        # 3. Stage files – we *always* git-add to ensure metadata gets updated.
        self.repo.git.add(doc_path.relative_to(self.root))
        # Add new blobs, too.
        if blobs_dir.exists():
            self.repo.git.add(blobs_dir.relative_to(self.root))

        # 4. Commit only if tree changed
        if not self.repo.is_dirty(untracked_files=True):
            return self.repo.head.commit.hexsha

        author = Actor(author_email, author_email)

        # Convert timestamp into ISO 8601 string for reproducibility.
        if isinstance(timestamp, (int, float)):
            ts_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        elif isinstance(timestamp, datetime):
            ts_dt = timestamp.astimezone(timezone.utc)
        else:
            raise TypeError("timestamp must be int, float, or datetime")

        ts_iso = ts_dt.isoformat()

        # Git expects "<Unix epoch> <tz offset>".
        epoch = int(ts_dt.timestamp())
        git_date_str = f"{epoch} +0000"

        commit = self.repo.index.commit(
            message=f"{doc_title} – imported revision at {ts_iso}",
            author=author,
            commit_date=git_date_str,
            author_date=git_date_str,
        )

        return commit.hexsha
