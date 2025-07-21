"""Thin wrapper around *google-api-python-client* for Drive access.

This keeps network code separate from the pure Git/HTML logic so we can run
unit tests without hitting Google.  All functions raise *ImportError* with a
friendly hint if the required Google libraries are missing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator, List, Tuple

SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _lazy_import():  # noqa: D401 – runtime dependency loader
    try:
        from google.oauth2.credentials import Credentials  # noqa: WPS433  (dynamic import)
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: WPS433
        from googleapiclient.discovery import build  # noqa: WPS433
    except ModuleNotFoundError as exc:  # pragma: no cover – runtime guard
        raise ImportError(
            "Google API libraries missing. Install with: pip install "
            "google-auth-oauthlib google-api-python-client"
        ) from exc

    return Credentials, InstalledAppFlow, build


def _branch_dir() -> Path:
    """Return ~/.branch, copying client_secrets.json there on first run."""

    path = Path.home().joinpath(".branch")
    path.mkdir(exist_ok=True)

    secret_src = Path.cwd().joinpath("client_secrets.json")
    secret_dst = path.joinpath("client_secrets.json")
    if secret_src.is_file() and not secret_dst.exists():
        secret_dst.write_bytes(secret_src.read_bytes())
    return path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def login(force: bool = False) -> Path:
    """Run a browser OAuth flow and store the refresh token.

    Returns the path of the saved ``creds.json`` file.
    """

    Credentials, InstalledAppFlow, _ = _lazy_import()

    creds_path = _branch_dir().joinpath("creds.json")
    if creds_path.exists() and not force:
        return creds_path

    branch_dir = _branch_dir()

    # Accept either location, but afterwards copy into ~/.branch for persistence.
    client_secrets = Path.cwd().joinpath("client_secrets.json")
    if not client_secrets.is_file():
        client_secrets = branch_dir.joinpath("client_secrets.json")

    if not client_secrets.is_file():
        raise FileNotFoundError(
            "client_secrets.json not found. Place it in project root or ~/.branch/."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    creds = flow.run_local_server(port=0)

    # Persist refresh token and copy client_secrets.json into ~/.branch for reuse.
    creds_path.write_text(creds.to_json())
    dst_secret = _branch_dir().joinpath("client_secrets.json")
    if not dst_secret.exists() and client_secrets.exists():
        dst_secret.write_bytes(client_secrets.read_bytes())
    return creds_path


def _load_creds():
    Credentials, _, _ = _lazy_import()
    creds_path = _branch_dir().joinpath("creds.json")
    if not creds_path.is_file():
        raise FileNotFoundError("No creds.json found – run `branch login` first.")
    data = json.loads(creds_path.read_text())
    return Credentials.from_authorized_user_info(data, SCOPES)


def _drive_service():
    _, _, build = _lazy_import()
    return build("drive", "v3", credentials=_load_creds(), cache_discovery=False)


def list_docs() -> List[dict[str, Any]]:
    """Return all non-trashed Google Docs visible to the user."""

    service = _drive_service()
    q = "mimeType='application/vnd.google-apps.document' and trashed = false"
    fields = "nextPageToken, files(id, name)"

    files: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        resp = (
            service.files()
            .list(q=q, fields=fields, pageToken=page_token, pageSize=1000)
            .execute()
        )
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def iter_revisions(
    file_id: str,
) -> Iterator[Tuple[str, bytes, str, str]]:
    """Yield (revisionId, html_bytes, modifiedTimeISO, authorEmail)."""

    service = _drive_service()

    # Fetch revision metadata first so we know the sort order.
    meta = (
        service.revisions()
        .list(
            fileId=file_id,
            fields="revisions(id, modifiedTime, lastModifyingUser(emailAddress))",
            pageSize=1000,
        )
        .execute()
    )

    # Google returns newest-first; we want oldest-first for chronological commits.
    for rev in sorted(meta.get("revisions", []), key=lambda r: r["modifiedTime"]):
        rev_id = rev["id"]
        email = rev.get("lastModifyingUser", {}).get("emailAddress", "unknown@example.com")

        Credentials, InstalledAppFlow, build = _lazy_import()  # to get HttpError safely
        from googleapiclient.errors import HttpError  # noqa: WPS433 – dynamic import

        try:
            # Obtain export link for HTML for this revision.
            rev_meta = (
                service.revisions()
                .get(fileId=file_id, revisionId=rev_id, fields="exportLinks")
                .execute()
            )

            html_url = rev_meta.get("exportLinks", {}).get("text/html")
            if not html_url:
                continue  # cannot export – skip

            http = service._http  # authorised httplib2.Http object
            resp, export = http.request(html_url)
            if resp.status != 200:
                continue
        except HttpError as err:  # pragma: no cover – network path
            if err.resp.status == 404:
                continue
            raise
        except HttpError as err:  # pragma: no cover – network path
            if err.resp.status == 404:  # revision not found (rare but documented)
                continue
            raise

        yield rev_id, export, rev["modifiedTime"], email
