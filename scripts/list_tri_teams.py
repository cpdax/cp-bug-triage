"""List all distinct Custom.TriTeam values used on recent Bug work items.

Useful for finding the exact strings to use in WIQL queries.

Usage:
    python scripts/list_tri_teams.py
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import requests
import tomllib

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main():
    with open(PROJECT_ROOT / ".streamlit" / "secrets.toml", "rb") as f:
        secrets = tomllib.load(f)
    devops = secrets["devops"]

    auth = base64.b64encode(f":{devops['pat']}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    base = devops["org_url"].rstrip("/")
    project = devops["project"]

    # WIQL: get IDs of recent bugs
    wiql = {
        "query": (
            "SELECT [System.Id] FROM workitems "
            "WHERE [System.WorkItemType] = 'Bug' "
            "AND [System.ChangedDate] >= @Today - 90 "
            "ORDER BY [System.ChangedDate] DESC"
        )
    }
    print("🔍 Fetching IDs of bugs changed in the last 90 days…")
    resp = requests.post(
        f"{base}/{project}/_apis/wit/wiql?api-version=7.1",
        headers=headers,
        json=wiql,
        timeout=30,
    )
    resp.raise_for_status()
    ids = [r["id"] for r in resp.json().get("workItems", [])][:200]
    print(f"   Got {len(ids)} bug IDs.\n")
    if not ids:
        print("No bugs found in the window. Try widening the date range.")
        return

    # Batch fetch the TriTeam field
    print("🔍 Fetching TriTeam values…")
    body = {"ids": ids, "fields": ["System.Id", "Custom.TriTeam", "System.State"]}
    resp = requests.post(
        f"{base}/{project}/_apis/wit/workitemsbatch?api-version=7.1",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()

    teams: dict[str, int] = {}
    states: dict[str, int] = {}
    for item in resp.json().get("value", []):
        f = item.get("fields", {})
        team = f.get("Custom.TriTeam") or "(unset)"
        teams[team] = teams.get(team, 0) + 1
        state = f.get("System.State") or "(unset)"
        states[state] = states.get(state, 0) + 1

    print(f"\n📋 Distinct Custom.TriTeam values (across {len(ids)} bugs):\n")
    for team, count in sorted(teams.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>4}  {team!r}")

    print(f"\n📋 Distinct System.State values (sanity check):\n")
    for state, count in sorted(states.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>4}  {state!r}")


if __name__ == "__main__":
    main()
