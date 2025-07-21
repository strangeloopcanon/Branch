"""Minimal CLI wrapper around *branch.sync* – enough for tests & demos."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from pathlib import Path

from datetime import datetime, timezone

from .sync import BranchRepo
from .drive import login as drive_login
from .drive import list_docs, iter_revisions
from .utils import slugify

import webbrowser
import difflib
import re
import tempfile
import subprocess
import html

# ------------------------------------------------------------------
# Paragraph-level visual diff
# ------------------------------------------------------------------


# ------------------------------------------------------------------
# Two-column diff with attributes stripped
# ------------------------------------------------------------------


def _clean_html(src: str) -> list[str]:
    """Return list of cleaned HTML lines suitable for HtmlDiff."""

    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(src, "html.parser")
        # Drop style / script blocks completely.
        for tag in soup(["style", "script"]):
            tag.decompose()
        # Remove all attributes from remaining elements.
        for tag in soup.find_all(True):
            tag.attrs = {}
        cleaned = soup.prettify()
    except Exception:
        # Regex fallback – remove style/script blocks and attributes.
        cleaned = re.sub(r"<style.*?</style>", "", src, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<script.*?</script>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<([a-zA-Z0-9]+)(\s[^>]*)?>", r"<\1>", cleaned)

    return cleaned.splitlines()

# ---------------------------------------------------------------------------
# Sub-command implementations
# ---------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace) -> None:  # noqa: D401 – CLI entry
    """Create (or reuse) a local Branch repository at *args.path*."""

    repo = BranchRepo(args.path)
    print(f"Initialised Branch repo at {repo.root}")


def _cmd_import(args: argparse.Namespace) -> None:  # noqa: D401 – CLI entry
    """Import a **single** HTML file as a new revision.

    This helper exists purely so automated tests can exercise the internal
    logic without relying on network access.  Typical usage::

        branch import path/to/doc.html --title "My Doc" \\
               --author user@example.com --timestamp 1700000000
    """

    html_path = Path(args.html).expanduser().resolve()
    if not html_path.is_file():
        sys.exit(f"error: HTML file not found: {html_path}")

    html = html_path.read_text(encoding="utf-8")

    repo = BranchRepo(args.repo)

    ts: int | float | datetime
    if args.timestamp is None:
        ts = datetime.now(tz=timezone.utc)
    else:
        try:
            ts = int(args.timestamp)
        except ValueError:
            # Try ISO-8601
            ts = datetime.fromisoformat(args.timestamp.rstrip("Z"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

    sha = repo.commit_revision(
        doc_title=args.title,
        html=html,
        author_email=args.author,
        timestamp=ts,
    )

    print(sha)


# ------------------------------------------------------------------
# Google-Drive sub-commands
# ------------------------------------------------------------------


def _cmd_login(_args: argparse.Namespace) -> None:  # noqa: D401 – CLI entry
    path = drive_login()
    print(f"Saved refresh token → {path}")


def _cmd_import_drive(args: argparse.Namespace) -> None:  # noqa: D401 – CLI entry
    repo = BranchRepo(args.repo)

    # We need the doc title first – fetch once via files.get.
    try:
        docs = {f["id"]: f["name"] for f in list_docs()}
        title = docs.get(args.file_id)
    except Exception as exc:  # pragma: no cover – network path
        sys.exit(f"error fetching doc metadata: {exc}")

    if not title:
        sys.exit("error: document not found or inaccessible")

    # If user left default repo path and it hasn't been created yet, derive
    # a nicer folder name from the document title.
    if args.repo == "./branch-repo" and not Path(args.repo).exists():
        derived = f"./{slugify(title)}-repo"
        args.repo = derived
        repo = BranchRepo(args.repo)

    print(f"Importing '{title}' …")

    imported = 0
    prev_head = repo.repo.head.commit.hexsha if repo.repo.head.is_valid() else None

    for rev_id, html_bytes, modified_iso, author in iter_revisions(args.file_id):
        ts = datetime.fromisoformat(modified_iso.rstrip("Z")).replace(tzinfo=timezone.utc)
        sha = repo.commit_revision(
            doc_title=title,
            html=html_bytes.decode(),
            author_email=author,
            timestamp=ts,
        )
        if sha != prev_head:
            imported += 1
            print(f"• rev {rev_id} → {sha}")
            prev_head = sha

    if imported == 0:
        print("Already up-to-date. No new revisions.")
    else:
        print(f"Synced {imported} new revision{'s' if imported != 1 else ''}.")


# ------------------------------------------------------------------
# sync = import-drive + show diff
# ------------------------------------------------------------------


def _open_latest_diff(repo: BranchRepo, slug: str) -> None:
    """Generate HTML diff for the last two commits of *slug* and open it."""

    doc_path = f"{slug}/doc.html"
    # Get last two commits touching that path.
    log = list(repo.repo.iter_commits(paths=doc_path, max_count=2))
    if len(log) < 2:
        print("(nothing to diff yet)")
        return

    latest, previous = log[0], log[1]
    a = previous.tree / doc_path
    b = latest.tree / doc_path
    html_a = a.data_stream.read().decode()
    html_b = b.data_stream.read().decode()

    def _html_to_text(src: str) -> list[str]:
        try:
            from bs4 import BeautifulSoup  # type: ignore

            soup = BeautifulSoup(src, "html.parser")
            for tag in soup(["style", "script"]):
                tag.decompose()
            text = soup.get_text()
        except Exception:
            text = re.sub(r"<[^>]+>", "", src)
        return text.splitlines()

    old_lines = _html_to_text(html_a)
    new_lines = _html_to_text(html_b)

    patch_text = "\n".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=previous.hexsha[:7],
            tofile=latest.hexsha[:7],
            lineterm="",
        )
    )

    # Pass through diff2html (requires npm install -g diff2html-cli)
    try:
        html_out = subprocess.check_output(
            [
                "diff2html",
                "-i",
                "stdin",
                "-o",
                "stdout",
                "--style",
                "line",
            ],
            input=patch_text,
            text=True,
        )
    except FileNotFoundError:
        print("diff2html CLI not found. Falling back to simple HtmlDiff.")
        html_out = difflib.HtmlDiff(wrapcolumn=120).make_file(
            old_lines,
            new_lines,
            fromdesc=previous.hexsha[:7],
            todesc=latest.hexsha[:7],
        )

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".html") as tmp:
        tmp.write(html_out)
        tmp_path = tmp.name

    webbrowser.open(f"file://{tmp_path}")


def _cmd_sync(args: argparse.Namespace) -> None:  # noqa: D401 – CLI entry
    # Determine repo path first (same logic as import-drive default tweak)
    try:
        docs = {f["id"]: f["name"] for f in list_docs()}
        title = docs.get(args.file_id)
    except Exception:
        title = None

    if args.repo == "./branch-repo" and title and not Path(args.repo).exists():
        args.repo = f"./{slugify(title)}-repo"

    # Reuse import-drive logic (now with possibly modified repo path)
    _cmd_import_drive(args)

    # Need slug for doc directory; fetch metadata again.
    if not title:
        return

    repo = BranchRepo(args.repo)
    _open_latest_diff(repo, slugify(title))


# ---------------------------------------------------------------------------
# Top-level argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:  # noqa: D401 – util
    p = argparse.ArgumentParser(prog="branch", description="Branch – Google Docs to Git synchroniser")

    sub = p.add_subparsers(dest="cmd", required=True)

    # branch init
    sp = sub.add_parser("init", help="initialise a new Branch repository")
    sp.add_argument("path", nargs="?", default="./branch-repo", help="path where the Git repo lives")
    sp.set_defaults(func=_cmd_init)

    # branch import
    sp = sub.add_parser("import", help="import a single HTML revision into the repo (offline mode)")
    sp.add_argument("html", help="path to the exported HTML file")
    sp.add_argument("--repo", default="./branch-repo", help="path to the local Branch repo")
    sp.add_argument("--title", required=True, help="document title")
    sp.add_argument("--author", default="unknown@example.com", help="author e-mail")
    sp.add_argument("--timestamp", help="POSIX seconds or ISO-8601 string (defaults: now)")
    sp.set_defaults(func=_cmd_import)

    # branch login (Google OAuth)
    sp = sub.add_parser("login", help="run Google OAuth flow to store refresh token")
    sp.set_defaults(func=_cmd_login)

    # branch import-drive
    sp = sub.add_parser("import-drive", help="import *all* revisions of a Google Doc")
    sp.add_argument("file_id", help="Drive file ID of the Google Doc")
    sp.add_argument("--repo", default="./branch-repo", help="path to the local Branch repo")
    sp.set_defaults(func=_cmd_import_drive)

    # branch sync (import + open diff)
    sp = sub.add_parser(
        "sync",
        help="import-drive then open latest diff in browser",
        description="Synchronise the Google Doc and open the diff between the two latest revisions",
    )
    sp.add_argument("file_id", help="Drive file ID of the Google Doc")
    sp.add_argument("--repo", default="./branch-repo", help="path to the local Branch repo")
    sp.set_defaults(func=_cmd_sync)

    return p


def main(argv: list[str] | None = None) -> None:  # noqa: D401 – CLI entry
    parser = _build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":  # pragma: no cover
    main()
