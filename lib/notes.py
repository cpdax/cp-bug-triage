"""Per-bug notes that survive Confluence page refreshes.

Notes live as second rows in the bug tables. Each note row's cell begins with
a marker `📝 #<BUG_ID> — ` followed by free-form text. That marker is what
lets us round-trip user-typed notes through full page replacements.

When a bug leaves Awaiting Tri-Team and its note can no longer be re-rendered
on the active triage pages, the note is appended to the team's archive page
so it isn't lost.

Editing flow:
    1. User clicks Edit on the Confluence page
    2. Clicks into any notes row beneath a bug
    3. Types after the marker
    4. Saves the page
On the next refresh, `extract_notes()` parses those rows back out and we
re-emit them in the new table.

Limitations:
    - Plain text only. Bold/italic/links typed inside a notes row are
      flattened on the next refresh.
    - The marker text must remain intact. If a user deletes the
      `📝 #23382 — ` prefix the note is orphaned and dropped on refresh.
    - If a bug appears in multiple sections (e.g., missing both PM and Eng
      fields), it has multiple notes rows. We treat the latest non-empty one
      as canonical and re-emit the same note in every section after refresh.
"""

from __future__ import annotations

import re
from datetime import datetime

try:
    from bs4 import BeautifulSoup, Tag
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore
    Tag = None  # type: ignore

# Marker pattern: 📝 #12345 — note text here
# Tolerates em-dash, en-dash, or plain hyphen as the separator.
NOTE_MARKER_RE = re.compile(
    r"📝\s*#(\d+)\s*[—\-–]\s*(.*)",
    re.DOTALL,
)

# Sentinel placeholder text used in freshly-created archive pages.
ARCHIVE_PLACEHOLDER_TEXT = "(no archived notes yet)"


def extract_notes(page_storage_html: str) -> dict[int, str]:
    """Parse a Confluence storage-format page and return {bug_id: note_text}.

    Looks for `<tr>` rows containing a single `<td>` with a colspan attribute
    whose text begins with the note marker. Empty notes (just the marker, no
    content) are skipped. Multiple matches for the same bug ID resolve to the
    last one found.
    """
    if not page_storage_html or BeautifulSoup is None:
        return {}

    notes: dict[int, str] = {}
    soup = BeautifulSoup(page_storage_html, "html.parser")
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 1:
            continue
        if not tds[0].get("colspan"):
            continue
        text = tds[0].get_text(separator=" ", strip=True)
        match = NOTE_MARKER_RE.match(text)
        if not match:
            continue
        bug_id = int(match.group(1))
        body = match.group(2).strip()
        if body:
            notes[bug_id] = body
    return notes


def render_notes_row(bug_id: int, note_text: str | None, colspan: int) -> str:
    """Render a single notes row for a bug.

    Empty notes still render so users have an obvious click target. The marker
    is wrapped in `<em>` for visual de-emphasis; the user-typed text follows
    as plain text. This shape is what `extract_notes` parses back on refresh.
    """
    safe_note = _escape(note_text or "")
    return (
        f'<tr><td colspan="{colspan}">'
        f'<em>📝 #{bug_id} — </em>{safe_note}'
        "</td></tr>"
    )


def notes_instruction_banner() -> str:
    """One-line callout explaining how to add notes."""
    return (
        '<div data-type="panel-info">'
        "<p>💡 <strong>To add a note:</strong> click <em>Edit</em>, then click into "
        "the row beneath any bug and type after the <code>📝 #BUGID — </code> marker. "
        "Notes persist across refreshes as long as the marker stays intact. "
        "Formatting (bold, italics, links) inside a note will be flattened on the next refresh."
        "</p></div>"
    )


# -----------------------------------------------------------------------------
# Archive page management
# -----------------------------------------------------------------------------

def archive_entry_html(
    *,
    bug_id: int,
    bug_title: str,
    bug_url: str,
    note_text: str,
    archived_date: str,
) -> str:
    """Render a single archive entry as `<li><p>…</p></li>`.

    Format:
        2026-04-30 · #23382 — Bug title here · Note text
    """
    label = f"#{bug_id}"
    if bug_title:
        label += f" — {_escape(bug_title)}"
    return (
        "<li><p>"
        f"<strong>{_escape(archived_date)}</strong> · "
        f'<a href="{_escape(bug_url)}">{label}</a> · '
        f"{_escape(note_text)}"
        "</p></li>"
    )


def prepend_archive_entries(
    existing_archive_html: str,
    new_entries_html: list[str],
) -> str:
    """Insert new archive entries at the top of the archive page's `<ul>`.

    - Locates the first `<ul>` after the introductory `<hr/>`.
    - Removes the placeholder `<li>` if present (text matches
      `ARCHIVE_PLACEHOLDER_TEXT`).
    - Prepends the new entries in the order given (so the first entry in the
      list ends up at the top of the page).
    - Returns the updated HTML as a string.

    If the page is missing a `<ul>` or BeautifulSoup is unavailable, returns
    the original HTML unchanged so we never destroy existing content.
    """
    if not new_entries_html:
        return existing_archive_html
    if not existing_archive_html or BeautifulSoup is None:
        return existing_archive_html

    soup = BeautifulSoup(existing_archive_html, "html.parser")
    ul = soup.find("ul")
    if not ul:
        return existing_archive_html

    # Remove placeholder if it exists. Match by visible text to be tolerant
    # of formatting variations.
    for li in ul.find_all("li", recursive=False):
        text = li.get_text(strip=True)
        if ARCHIVE_PLACEHOLDER_TEXT in text:
            li.decompose()

    # Parse and insert new <li> elements at the top, in order.
    # Reverse the list so we can repeatedly insert(0, …) and end up with the
    # first input entry at the top.
    for entry_html in reversed(new_entries_html):
        fragment = BeautifulSoup(entry_html, "html.parser")
        new_li = fragment.find("li")
        if new_li is None:
            continue
        ul.insert(0, new_li)

    return str(soup)


def today_iso_date() -> str:
    """Today's date in YYYY-MM-DD, Eastern Time."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d")


def _escape(s: str) -> str:
    if not s:
        return ""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
