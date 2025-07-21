## Product Requirements Document – **“Branch”**

## “Branch” – pared‑down spec

### 1 Goal

Ship a self‑hosted utility that **pulls existing Google Docs into a local Git repo** and keeps them in sync.
*One‑click Google login → pick docs → auto‑generate history → run `git diff` whenever you want.*

---

### 2 User flow

| Step                  | Action                                                                        | Behind the scenes                                                                                                                                                                                                                              |
| --------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Launch**         | `branch gui` (Electron) or `branch import <Drive‑folder‑ID>` (CLI). | Opens localhost:3000.                                                                                                                                                                                                                          |
| **2. OAuth**          | Click “Sign in with Google”.                                                  | Requests scopes: `drive.readonly`, `drive.metadata.readonly`. Stores refresh token in `~/.branch/creds.json`.                                                                                                                             |
| **3. Select docs**    | Checkboxes appear for Docs you own or can read.                               | Saves chosen `fileId`s in `config.yaml`.                                                                                                                                                                                                       |
| **4. Import**         | Hit **Start**.                                                                | For each doc:<br>• List all `revisions`.<br>• For each revision `r`:<br> • `drive.revisions.get(r).exportLinks["text/html"]`.<br> • Normalise HTML, strip base64 images to `/blobs/sha256`.<br> • `git commit --author="$email" --date="$ts"`. |
| **5. Diff / restore** | Open the generated local repo in any Git client.                              | Nothing special—Git handles diffs, blame, checkout.                                                                                                                                                                                            |
| **6. Sync loop**      | `branch daemon` runs every 60 mins.                                         | Polls Drive `changes.list` for new revisions → repeats step 4.                                                                                                                                                                                 |

---

### 3 Scope

| Included (v0.1)           | Excluded                    |
| ------------------------- | --------------------------- |
| Google Docs only          | Sheets, Slides              |
| HTML export ≤ 10 MB       | Big media docs (deal later) |
| Single‑user token         | Multi‑tenant, SAML          |
| Local filesystem Git repo | Server SaaS, S3, Postgres   |
| CLI + minimal web picker  | Full PR UI, comments        |

---

### 4 Tech stack

* **Python 3.12** – requests, google‑api‑python‑client, `gitpython`.
* **TOML config** – no database; state lives under `~/.branch/`.
* **Git CLI** – treat each Doc as a sub‑directory containing `doc.html` plus `blobs/`.
* **Electron (optional)** – thin wrapper around React picker; everything else is CLI‑driven.
* **diffDOM** – only for generating a readable side‑by‑side HTML diff in `branch diff <doc> <rev1> <rev2>`; otherwise users rely on native Git tools.

---

### 5 Directory layout

```
~/Documents/Branch/
  repo/.git/
  repo/<doc-title-slug>/
       blobs/<sha256>
       doc.html          # working tree = latest head
```

Each Git commit reproduces the entire `doc.html`; blobs are hard‑linked so history is space‑efficient.

---

### 6 Edge cases & simple answers

| Problem                        | Cheap answer                                                         |
| ------------------------------ | -------------------------------------------------------------------- |
| **10 MB export cap**           | Detect oversize; log warning; skip image stripping for now.          |
| **Binary images blow up repo** | Deduplicate by SHA + `.gitattributes` pointer; ignore granular diff. |
| **Revision IDs collapse**      | You’ve already copied bytes—loss upstream doesn’t matter.            |
| **OAuth token expiry**         | Refresh silently; if fails, prompt “Re‑login”.                       |

---

### 7 Installation (macOS/Linux)

```bash
pip install branch
branch login            # opens browser for OAuth
branch import <folderID>
cd branch-repo
git log --graph --all
```

Windows: ship a single‑file PyInstaller bundle with Git‑for‑Windows embedded.

---

### 8 What you get day 1

* Unlimited local history for chosen Docs.
* Works offline: Git repo is plain files.
* Any Git GUI (VS Code, Fork, Sourcetree) shows diffs; no custom UI required.
* Minimal footprint: no server, no database, no Docker.
* Easy to nuke: delete the folder.

---

### 9 Next small upgrades (once basics work)

1. **Auto‑open diff link** after each sync (`git difftool --tool=browser`).
2. **Optional push** to GitHub remote so others can clone.
3. **Shadow‑doc branching**: clone Doc when user runs `branch branch new‑idea`.

Keep everything else—compliance, CRDT, web PRs—off the roadmap until real users ask.
