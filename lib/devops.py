"""Azure DevOps client.

Uses Azure DevOps REST API v7.1. Authenticates via PAT in HTTP Basic header.
Reference: https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import requests


@dataclass
class WorkItem:
    """Lightweight representation of an ADO bug. Only the fields we need."""

    id: int
    title: str
    state: str
    assigned_to: str | None
    created_date: str  # ISO 8601
    changed_date: str  # ISO 8601
    area_path: str
    tags: list[str] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return self.fields.get("_url", "")


class DevOpsClient:
    """Read-only client for Azure DevOps work item queries.

    Usage:
        client = DevOpsClient(org_url, project, pat)
        items = client.fetch_by_wiql(wiql_query_string)
    """

    def __init__(self, org_url: str, project: str, pat: str):
        self.org_url = org_url.rstrip("/")
        self.project = project
        self.pat = pat
        self._session = requests.Session()
        token = base64.b64encode(f":{pat}".encode()).decode()
        self._session.headers.update(
            {
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _api(self, path: str) -> str:
        return f"{self.org_url}/{self.project}/_apis/{path}"

    def fetch_by_wiql(self, wiql: str) -> list[WorkItem]:
        """Run an inline WIQL query and return hydrated work items.

        Two-step:
          1. POST WIQL to get matching work item IDs
          2. POST workitemsbatch with those IDs to get full fields
        """
        # Step 1: run WIQL
        wiql_url = self._api("wit/wiql?api-version=7.1")
        resp = self._session.post(wiql_url, json={"query": wiql}, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        ids = [row["id"] for row in data.get("workItems", [])]
        if not ids:
            return []

        # Step 2: hydrate in batches of 200 (ADO limit)
        items: list[WorkItem] = []
        for i in range(0, len(ids), 200):
            batch_ids = ids[i : i + 200]
            batch = self._fetch_batch(batch_ids)
            items.extend(batch)
        return items

    def _fetch_batch(self, ids: list[int]) -> list[WorkItem]:
        url = self._api("wit/workitemsbatch?api-version=7.1")
        body = {"ids": ids, "fields": [], "$expand": "all"}
        resp = self._session.post(url, json=body, timeout=30)
        resp.raise_for_status()
        return [self._parse_work_item(raw) for raw in resp.json().get("value", [])]

    def _parse_work_item(self, raw: dict[str, Any]) -> WorkItem:
        f = raw.get("fields", {})
        assigned = f.get("System.AssignedTo")
        if isinstance(assigned, dict):
            assigned_name = assigned.get("displayName")
        else:
            assigned_name = assigned

        tags_raw = f.get("System.Tags", "") or ""
        tags = [t.strip() for t in tags_raw.split(";") if t.strip()] if tags_raw else []

        wi = WorkItem(
            id=raw["id"],
            title=f.get("System.Title", ""),
            state=f.get("System.State", ""),
            assigned_to=assigned_name,
            created_date=f.get("System.CreatedDate", ""),
            changed_date=f.get("System.ChangedDate", ""),
            area_path=f.get("System.AreaPath", ""),
            tags=tags,
            fields=f,
        )
        wi.fields["_url"] = (
            f"{self.org_url}/{self.project}/_workitems/edit/{wi.id}"
        )
        return wi
