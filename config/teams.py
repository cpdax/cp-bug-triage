"""Per-team configuration: Confluence page IDs, ADO TriTeam values.

Each team is keyed by a short slug used in the UI. The `owner_label` field is
purely cosmetic — it appears as hint text in the team checkbox list so users
remember whose space is whose. It has no functional effect on the refresh.

Bug queries are constructed inline at runtime using the WIQL templates below.
No saved queries in DevOps required.
"""

# -----------------------------------------------------------------------------
# Teams — one entry per CP tri-team.
# -----------------------------------------------------------------------------
# tri_team_value is the exact string stored in Custom.TriTeam on bugs.
# Confirmed via list_tri_teams.py on 2026-04-30.
# -----------------------------------------------------------------------------

TEAMS = {
    "communication": {
        "display_name": "CP Communication",
        "owner_label": "Amy",
        "tri_team_value": "Team CPC (ChildPlus Connect)",
        "confluence": {
            "space_key": "CPC",
            "space_id": "2780069895",
            "parent_page_id": "4068278285",
            "current_page_id": "4068278306",
            "historical_page_id": "4067295303",
            "archive_page_id": "4067786794",
        },
    },
    "migration": {
        "display_name": "CP Migration",
        "owner_label": "Amy",
        "tri_team_value": "Team ABE (Conversion Items)",
        "confluence": {
            "space_key": "ABE",
            "space_id": "2684813364",
            "parent_page_id": "4067426351",
            "current_page_id": "4068147228",
            "historical_page_id": "4068114464",
            "archive_page_id": "4067295365",
        },
    },
    "online": {
        "display_name": "CP Online",
        "owner_label": "Justina",
        "tri_team_value": "Team C-JAN (Online Improvements)",
        "confluence": {
            "space_key": "JAN",
            "space_id": "2684846095",
            "parent_page_id": "4068311050",
            "current_page_id": "4067459088",
            "historical_page_id": "4067000363",
            "archive_page_id": "4067426417",
        },
    },
    "platform": {
        "display_name": "CP Platform",
        "owner_label": "Justina",
        "tri_team_value": "Team JST (Platform Improvements)",
        "confluence": {
            "space_key": "JST",
            "space_id": "2778529897",
            "parent_page_id": "4067655715",
            "current_page_id": "4067360797",
            "historical_page_id": "4067295324",
            "archive_page_id": "4066836533",
        },
    },
}


# -----------------------------------------------------------------------------
# WIQL templates — formatted at runtime with each team's tri_team_value.
# -----------------------------------------------------------------------------
# State value is "Awaiting Tri-Team" with a hyphen (confirmed via dump_bug.py).
# 365-day cutoff splits Current vs Historical based on bug creation date.
# -----------------------------------------------------------------------------

WIQL_CURRENT = """\
SELECT [System.Id]
FROM workitems
WHERE [System.WorkItemType] = 'Bug'
  AND [System.State] = 'Awaiting Tri-Team'
  AND [Custom.TriTeam] = '{tri_team_value}'
  AND [System.CreatedDate] >= @Today - 365
ORDER BY [System.CreatedDate] DESC
"""

WIQL_HISTORICAL = """\
SELECT [System.Id]
FROM workitems
WHERE [System.WorkItemType] = 'Bug'
  AND [System.State] = 'Awaiting Tri-Team'
  AND [Custom.TriTeam] = '{tri_team_value}'
  AND [System.CreatedDate] < @Today - 365
ORDER BY [System.CreatedDate] DESC
"""


def wiql_for(team_key: str, kind: str) -> str:
    """Build the WIQL string for a given team + kind ('current' or 'historical')."""
    team = TEAMS[team_key]
    template = WIQL_CURRENT if kind == "current" else WIQL_HISTORICAL
    return template.format(tri_team_value=team["tri_team_value"])
