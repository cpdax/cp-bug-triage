"""Field requirements for clearing the `Awaiting Tri Team` status.

Confirmed with Amy Smith and Justina Stein on 2026-04-30:
  - PM owns: Product Score, Acceptance Criteria
  - Eng owns: T-shirt Size
  - Design owns: Design/Solution (only when bug is tagged "Needs Design")

Priority is set by Steve before bugs reach Awaiting Tri Team, so it's
displayed as a column but not checked as a required field.

# REFERENCE NAME VERIFICATION
# These are best-guess based on the field display names visible in the DevOps
# UI. Verify by running: python scripts/verify_fields.py
# Or by hitting:
#   GET https://{org}.visualstudio.com/{project}/_apis/wit/workitemtypes/Bug/fields?api-version=7.1
# If any of these are wrong, the app will report missing fields for every bug.
"""

FIELD_REQUIREMENTS = [
    {
        "key": "product_score",
        "role": "pm",
        "label": "Product Score",
        "ado_field": "Custom.ProductScore",
        "check": "non_empty",
        "conditional": False,
    },
    {
        "key": "acceptance_criteria",
        "role": "pm",
        "label": "Acceptance Criteria",
        "ado_field": "Microsoft.VSTS.Common.AcceptanceCriteria",
        "check": "non_empty",
        "conditional": False,
    },
    {
        "key": "tshirt_size",
        "role": "eng",
        "label": "T-shirt Size",
        "ado_field": "Custom.TShirtSize",
        "check": "non_empty",
        "conditional": False,
    },
    {
        "key": "design_solution",
        "role": "design",
        "label": "Design/Solution",
        "ado_field": "Custom.DesignSolution",
        "check": "non_empty",
        "conditional": True,  # only counts when bug has the Needs Design tag
    },
]

# Bug is "needs design" when this tag is present in System.Tags.
# Confirmed by Justina 2026-04-30: tag text is exactly "Needs Design".
# Tag matching in this app is case-insensitive but otherwise literal.
DESIGN_FLAG_TAG = "Needs Design"

# Standard ADO field. Displayed as a column on every triage table.
PRIORITY_FIELD = "Microsoft.VSTS.Common.Priority"

# Useful for query construction — bugs carry a "Tri Team" field that names
# the owning team, so queries can filter by [Custom.TriTeam] = 'CP Online'
# rather than relying on area path. Not used directly in field evaluation.
TRI_TEAM_FIELD = "Custom.TriTeam"
