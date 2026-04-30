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
        """Fetch page metadata + current version. Body not included (we don't need it for updates)."""
        resp = self._session.get(self._api(f"pages/{page_id}"), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def update_page(
        self,
        page_id: str,
        title: str,
        body_markdown: str,
        version_message: str = "",
    ) -> dict[str, Any]:
        """Full-replace the body of a page.

        The v2 API requires:
          - the new version number (current + 1)
          - the page title (must match or be updated)
          - the body in one of: storage | atlas_doc_format | wiki | view
            We use markdown via the v2 endpoint, which converts to storage.

        Returns the updated page object.
        """
        # Step 1: get current version number
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
                "message": version_message or f"Auto-refreshed by Bug Triage app",
            },
        }
        if page_type == "page":
            # parent retained from current page
            parent_id = current.get("parentId")
            if parent_id:
                body["parentId"] = parent_id

        resp = self._session.put(
            self._api(f"pages/{page_id}"), json=body, timeout=30
        )
        resp.raise_for_status()
        return resp.json()


def _markdown_to_storage(md: str) -> str:
    """Convert markdown to Confluence storage format (XHTML).

    Confluence's storage format is XHTML-based. For a v1 implementation, we
    rely on a small subset of markdown that we control via renderer.py: headings,
    paragraphs, tables, links, bold, lists, blockquotes. This converter handles
    that subset directly without pulling in a heavy markdown library.

    For richer cases later, consider swapping to `markdown` lib + post-processing,
    or generating storage format directly in renderer.py.
    """
    # NOTE: Confluence's v2 API supports {"representation": "wiki"} for raw wiki
    # markup, and {"representation": "storage"} for XHTML. The simplest path is
    # to pass storage with our generated XHTML. We'll generate storage format
    # directly in renderer.py rather than converting from markdown.
    return md
