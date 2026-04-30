# CP Bug Triage

A Streamlit app for refreshing per-team bug triage Confluence pages from Azure DevOps queries. Built for the four ChildPlus tri-teams (Communication, Migration, Online, Platform).

**Owners:** Amy Smith (Communication, Migration), Justina Stein (Online, Platform). The app is owned by Product Operations (Dax Collins).

---

## What it does

1. PM opens the bookmarked URL and enters the shared app password.
2. Picks themselves from the owner picker.
3. Picks a team (or both teams).
4. Hits the big red REFRESH button.
5. App pulls bugs in `Awaiting Tri Team` status from Azure DevOps, splits them into Current (<365 days old) and Historical (>365 days old), evaluates which fields are missing per bug, groups by responsible party (PM / Eng / Design), and full-replaces the team's two Confluence triage pages.
6. Confirmation displays in-app with counts and links.

---

## Local development

```bash
# Clone
git clone https://github.com/cpdax/cp-bug-triage.git
cd cp-bug-triage

# Set up Python environment
python3 -m venv .venv
source .venv/bin/activate  # on Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit .streamlit/secrets.toml with real values

# Run
streamlit run app.py
```

App opens at http://localhost:8501.

---

## Authentication

This app uses a **shared password gate**. Anyone with the password can use the app.

The password lives in `secrets.toml` under `[access].password`. Pick something memorable but not guessable, share it with Amy and Justina via Slack DM (not in any persistent channel). Rotate periodically.

> **Future enhancement:** Microsoft Entra OAuth via Streamlit's native OIDC support is the better long-term auth model — it gives per-user audit logs and removes the shared-secret problem. Skipped for v1 because Procare's Entra tenant restricts app registrations to admins. Revisit if scope grows or if app registration permissions are granted. Notes for the future implementation are preserved in the project working notes.

---

## Streamlit Community Cloud deploy

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io and sign in with GitHub.
3. **Create app** → point at this repo, branch `main`, file `app.py`.
4. **Advanced settings → Secrets:** paste the contents of your local `secrets.toml` (Streamlit Cloud doesn't read the file from the repo — secrets are managed in their UI).
5. Deploy. Note the URL it assigns (e.g., `https://cp-bug-triage.streamlit.app`).
6. Bookmark and share the URL + password with Amy and Justina.

---

## Configuration

### Teams
`config/teams.py` — Confluence page IDs and ADO query IDs per team. Page IDs are filled in. ADO query IDs are placeholders until the queries are written.

### Field requirements
`config/fields.py` — what counts as "filled" on a bug for it to clear `Awaiting Tri Team`. Currently a placeholder definition. Replace with the real list once Amy and Justina deliver it.

### Owners
`config/teams.py → OWNERS` — display name, title, tagline, and avatar path for the picker. Replace `static/avatars/amy.png` and `static/avatars/justina.png` with real photos before deploying. Their Outlook profile pictures are fine.

---

## Architecture

```
app.py                    Streamlit UI + password gate
config/
  teams.py                Per-team config (page IDs, query IDs, ownership)
  fields.py               Field requirements for Awaiting Tri Team
lib/
  devops.py               Azure DevOps REST client (read-only)
  confluence.py           Confluence REST client (full-replace pages)
  triage.py               Field evaluation logic (pure functions)
  renderer.py             Build Confluence storage-format page bodies
static/
  avatars/                Owner profile photos
```

Auth is a shared password stored in Streamlit secrets. ADO uses PAT auth via HTTP Basic. Confluence uses Atlassian API token auth via HTTP Basic.

---

## Maintenance

- **PAT rotation:** the DevOps PAT and Confluence API token both expire. Set calendar reminders. Rotation = generate new value, paste into Streamlit Cloud secrets, save (auto-redeploys).
- **Password rotation:** rotate periodically. Update the `[access].password` secret in Streamlit Cloud and notify Amy and Justina.
- **Adding a team:** add an entry to `TEAMS` in `config/teams.py` with its Confluence page IDs and ADO query IDs. Add the owner if they're new.
- **Changing field requirements:** edit `config/fields.py`. Live for the next refresh after the next push.

---

## Status

🚧 **In development.** Pending before this is functional:
- ADO query IDs (Dax to write per-team queries)
- DevOps PAT generation
- Confluence API token generation
- Real field requirement list (waiting on Amy + Justina)
- Owner avatar photos (their Outlook profile pics)
- Shared password chosen and shared with Amy and Justina
- First Streamlit Cloud deploy
