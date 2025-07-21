# Branch – Google Docs → Git synchroniser (v0.1)

`branch` lets you pull the full revision history of one-or-more Google Docs
into a **local Git repository**.  You can then use any Git tool (CLI, VS Code,
Fork, …) to diff, blame, branch or push the docs like normal source code.

This repo implements the minimal workflow described in *PRD.md*:

1. A one-time Google OAuth login (`branch login`).
2. Import **all** revisions of a Doc into a Git repo (`branch import-drive`).
3. Optional offline import of a single HTML file (`branch import`).

No servers or databases – just plain files under `~/.branch/` and whatever Git
repository directory you choose.

---

## Quick start

### 0. Prerequisites

```bash
# Python bits
python -m pip install gitpython google-auth-oauthlib google-api-python-client

# Optional – prettier browser diff (requires Node.js)
npm install -g diff2html-cli
```

### 1. Google Cloud credentials

1. Create an **OAuth 2.0 Client ID** (type *Desktop*) in Google Cloud Console.
2. Download the JSON and save it in the project root as `client_secrets.json`.

Running `branch login` once will automatically move that file to
`~/.branch/client_secrets.json`.

### 2. Authenticate

```bash
python -m branch login
# → Browser opens; grant Drive read-only scopes.
```

### 3. Quick sync & diff (recommended)

```bash
# One-liner: pull new revisions *and* open latest diff in browser
python -m branch sync FILE_ID
```

If this is the first time you sync the doc, a repository folder named
`<doc-title>-repo` is created automatically in the current directory.  Next
invocations reuse the same repo.

### 4. Import once (full history) without showing diff

```bash
# Replace FILE_ID with the long ID in docs.google.com/document/d/FILE_ID/edit
python -m branch import-drive FILE_ID --repo ~/branch-repo
```

The command walks every Drive revision (oldest → newest) and commits it to
`~/branch-repo/<slug>/doc.html`.  Inline images are stripped out and stored as
dediuplicated `blobs/<sha256>` files.

### 5. Inspect history manually

```bash
cd ~/branch-repo
git log --graph --all -- <slug>/doc.html
```

---

## Offline importer (optional)

If you already have an HTML export of a Google Doc:

```bash
python -m branch init ~/branch-offline
python -m branch import exported.html \
        --title "My Doc" --author me@example.com --repo ~/branch-offline
```

---

## Notes

*   There's an open question on whether converting everything to Markdown might be a good idea.
