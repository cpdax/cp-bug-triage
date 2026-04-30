"""Confluence client — focused on what we need: full-replace of page bodies.

Uses Confluence Cloud REST API v2. Authenticates via Atlassian API token in
HTTP Basic auth (email + token).

Reference: https://developer.atlassian.com/cloud/confluence/rest/v2/
"""

from __future__ import annotations

import base64
from typing import Any

import requests


class ConfluenceClient:
    """Minimal Confluence client for reading and updating pages."""

    def __init__(self, base_url: str, email: str, api_token: str):
        # base_url should be like https://procare.atlassian.net/wiki
        self.base_url = base_url.rstrip("/")
        self._session = requests.Session()
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._session.headers.update(
            {
                "Authorization": f"Basic {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _api(self, path: str) -> str:
        return f"{self.base_url}/api/v2/{path}"

    def get_page(self, page_id: str) -> dict[str, Any]:
        """Fetch page metadata + current version. Body not included."""
        resp = self._session.get(self._api(f"pages/{page_id}"), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def fetch_page_storage(self, page_id: str) -> str:
        """Return the storage-format XHTML body of the page.

        Used to read existing page content before a refresh so per-bug notes
        can be preserved through the full-replace.
        """
        url = self._api(f"pages/{page_id}?body-format=storage")
        resp = self._session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("body", {}).get("storage", {}).get("value", "") or ""

    def update_page(
        self,
        page_id: str,
        title: str,
        body_markdown: str,
        version_message: str = "",
    ) -> dict[str, Any]:
        """Full-replace the body of a page.

        The v2 API requires the new version number (current + 1), the page
        title, and the body in one of: storage | atlas_doc_format | wiki | view.
        We use storage format with our own generated XHTML.

        Returns the updated page object.
        """
        current = self.get_page(page_id)
        next_version = current["version"]["number"] + 1
        page_type = current.get("type", "page")
        space_id = current.get("spaceId")

        body = {
            "id": page_id,
            "status": "current",
            "title": title,
            "spaceId": space_id,
            "body": {
                "representation": "storage",
                "value": _markdown_to_storage(body_markdown),
            },
            "version": {
                "number": next_version,
                "message": version_message or "Auto-refreshed by Bug Triage app",
            },
        }
        if page_type == "page":
            parent_id = current.get("parentId")
            if parent_id:
                body["parentId"] = parent_id

        resp = self._session.put(
            self._api(f"pages/{page_id}"), json=body, timeout=30
        )
        resp.raise_for_status()
        return resp.json()


def _markdown_to_storage(md: str) -> str:
    """Pass-through. The renderer emits storage-format XHTML directly."""
    return md
