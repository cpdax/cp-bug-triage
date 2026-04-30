"""Verify ADO field reference names match what the app expects.

Run this before deploying to confirm the field names in config/fields.py
actually exist on Bug work items in your Azure DevOps project.

Usage:
    python scripts/verify_fields.py

Reads credentials from .streamlit/secrets.toml.
Prints a table showing each expected field, whether ADO knows about it,
fuzzy matches for misses, and a full custom-field dump for manual lookup.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import requests
import tomllib  # Python 3.11+

# Make project root importable when run from anywhere
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.fields import (  # noqa: E402
    DESIGN_FLAG_TAG,
    FIELD_REQUIREMENTS,
    PRIORITY_FIELD,
    TRI_TEAM_FIELD,
)


def load_secrets() -> dict:
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        print(f"❌ secrets.toml not found at {secrets_path}")
        sys.exit(1)
    with open(secrets_path, "rb") as f:
        return tomllib.load(f)


def fetch_bug_fields(org_url: str, project: str, pat: str) -> list[dict]:
    """Get the list of fields available on Bug work items."""
    auth = base64.b64encode(f":{pat}".encode()).decode()
    url = f"{org_url.rstrip('/')}/{project}/_apis/wit/workitemtypes/Bug/fields"
    resp = requests.get(
        url,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
        params={"api-version": "7.1"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("value", [])


def find_fuzzy_matches(needle: str, fields: list[dict]) -> list[dict]:
    """Find fields whose name OR reference name contains any keyword from the needle."""
    keywords = [
        w.lower()
        for w in needle.replace("-", " ").replace("/", " ").split()
        if len(w) > 2
    ]
    if not keywords:
        return []
    matches = []
    seen = set()
    for f in fields:
        ref = f.get("referenceName", "")
        name = f.get("name", "")
        haystack = f"{ref} {name}".lower()
        if any(kw in haystack for kw in keywords):
            if ref not in seen:
                seen.add(ref)
                matches.append(f)
    return matches


def main():
    secrets = load_secrets()
    devops = secrets["devops"]

    print(f"🔍 Fetching Bug field list from {devops['org_url']}/{devops['project']}…\n")
    try:
        fields = fetch_bug_fields(devops["org_url"], devops["project"], devops["pat"])
    except requests.HTTPError as e:
        print(f"❌ ADO API error: {e}")
        print("   Check org_url and project in secrets.toml")
        sys.exit(1)
    except requests.RequestException as e:
        print(f"❌ Connection error: {e}")
        sys.exit(1)

    by_ref = {f["referenceName"]: f for f in fields}

    expected = [
        ("Product Score", FIELD_REQUIREMENTS[0]["ado_field"]),
        ("Acceptance Criteria", FIELD_REQUIREMENTS[1]["ado_field"]),
        ("T-shirt Size", FIELD_REQUIREMENTS[2]["ado_field"]),
        ("Design/Solution", FIELD_REQUIREMENTS[3]["ado_field"]),
        ("Priority", PRIORITY_FIELD),
        ("Tri Team", TRI_TEAM_FIELD),
    ]

    print(f"{'Display name':<22} {'Expected ref name':<45} {'Status':<8}")
    print("-" * 80)

    misses: list[tuple[str, str]] = []
    for display, expected_ref in expected:
        if expected_ref in by_ref:
            print(f"{display:<22} {expected_ref:<45} ✅ OK")
        else:
            print(f"{display:<22} {expected_ref:<45} ❌ MISS")
            misses.append((display, expected_ref))

    print()

    if misses:
        print("🔎 Fuzzy matches for missing fields:\n")
        for display, _ in misses:
            print(f"  Looking for fields related to '{display}':")
            candidates = find_fuzzy_matches(display, fields)
            if not candidates:
                print(f"    (no fields contain those keywords)")
            else:
                for c in candidates[:10]:
                    print(f"    referenceName = {c['referenceName']!r:<45}  name = {c['name']!r}")
            print()

    # Always dump the full custom field list — useful for manual lookup
    custom_fields = sorted(
        [f for f in fields if not f["referenceName"].startswith("System.")],
        key=lambda x: x["referenceName"],
    )

    # Write to a file for easy review
    dump_path = PROJECT_ROOT / "scripts" / "all_fields.txt"
    with open(dump_path, "w") as f:
        f.write("# All non-System fields on Bug work items\n")
        f.write(f"# Source: {devops['org_url']}/{devops['project']}\n\n")
        for fld in custom_fields:
            f.write(f"{fld['referenceName']}\t{fld['name']}\n")
    print(f"📋 Full field dump written to {dump_path}")
    print(f"   ({len(custom_fields)} non-System fields total)\n")

    # Also print Custom.* fields and any field with "size", "shirt", "estimate", "effort", "story" to console
    print("📋 Likely candidates (Custom.* fields + anything sizing-related):\n")
    keyword_filter = ["size", "shirt", "estimate", "effort", "story", "scheduling"]
    shown = 0
    for fld in custom_fields:
        ref = fld["referenceName"]
        name = fld["name"]
        is_custom = ref.startswith("Custom.")
        is_keyword = any(k in (ref + " " + name).lower() for k in keyword_filter)
        if is_custom or is_keyword:
            print(f"  {ref:<55} {name}")
            shown += 1
    if shown == 0:
        print("  (no Custom.* or sizing-related fields found — see all_fields.txt)")
    print()

    print(f"Tag check — DESIGN_FLAG_TAG = '{DESIGN_FLAG_TAG}'")
    print("  (tags are validated at runtime, not via this API)")
    print()

    if not misses:
        print("✅ All field reference names verified.")
    else:
        print("⚠️  Update the failed reference name(s) in config/fields.py based on the")
        print("    candidates above (or check scripts/all_fields.txt), then re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()
