"""Dump all non-empty fields on a specific bug.

Useful when you need to figure out which ADO field stores a particular value
(e.g., "what field is the t-shirt size actually in?").

Usage:
    python scripts/dump_bug.py <BUG_ID>

Example:
    python scripts/dump_bug.py 12834
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import requests
import tomllib

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_secrets() -> dict:
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    with open(secrets_path, "rb") as f:
        return tomllib.load(f)


def fetch_bug(org_url: str, project: str, pat: str, bug_id: str) -> dict:
    auth = base64.b64encode(f":{pat}".encode()).decode()
    url = f"{org_url.rstrip('/')}/{project}/_apis/wit/workitems/{bug_id}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
        params={"api-version": "7.1", "$expand": "all"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/dump_bug.py <BUG_ID>")
        sys.exit(1)
    bug_id = sys.argv[1]
    secrets = load_secrets()
    devops = secrets["devops"]

    print(f"🔍 Fetching bug #{bug_id}…\n")
    bug = fetch_bug(devops["org_url"], devops["project"], devops["pat"], bug_id)

    fields = bug.get("fields", {})
    print(f"Title: {fields.get('System.Title', '(no title)')}")
    print(f"State: {fields.get('System.State', '(unknown)')}")
    print(f"Type:  {fields.get('System.WorkItemType', '(unknown)')}")
    print()
    print(f"All non-empty fields ({len(fields)} total):\n")

    # Sort by reference name, but show non-System custom fields first
    items = sorted(fields.items(), key=lambda kv: (
        not kv[0].startswith("Custom."),
        kv[0],
    ))
    for ref, value in items:
        # Truncate long values
        if isinstance(value, dict):
            display = value.get("displayName") or value.get("uniqueName") or str(value)
        else:
            display = str(value)
        if len(display) > 100:
            display = display[:100] + "…"
        print(f"  {ref:<55} = {display}")


if __name__ == "__main__":
    main()
