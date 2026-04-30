"""Render bug evaluations into Confluence-friendly HTML.

Builds the page body that gets written to Confluence. Uses plain HTML
(headings, paragraphs, tables, lists) which renders cleanly in Confluence
storage format without needing macro markup.

Reference: https://developer.atlassian.com/cloud/confluence/storage-format-for-confluence-cloud/
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

from dateutil import parser as date_parser

from lib.notes import notes_instruction_banner, render_notes_row
from lib.triage import (
    BugEvaluation,
    filter_by_role,
    ready_to_advance,
    summary_stats,
)

ROLE_LABELS = {
    "pm": "PM",
    "eng": "Engineering",
    "design": "Design",
}

# Short labels used in the Missing column to keep cells readable.
ROLE_SHORT_LABELS = {
    "pm": "PM",
    "eng": "Eng",
    "design": "Design",
}

PRIORITY_EMOJI = {
    "1": "🔴",
    "2": "🟠",
    "3": "🟡",
    "4": "⚪",
}

AC_PREVIEW_CHARS = 250


def render_page(
    *,
    team_display_name: str,
    page_kind: str,  # "Current" or "Historical"
    evaluations: list[BugEvaluation],
    refreshed_by: str,
    notes: dict[int, str] | None = None,
) -> tuple[str, str]:
    """Build (title, body) for one Confluence page.

    The optional `notes` dict, if supplied, maps bug ID to note text. Notes
    are interleaved as a second row beneath each bug's main row.
    """
    notes = notes or {}
    title = f"{page_kind} Bugs — {team_display_name}"
    timestamp = _now_eastern_string()
    stats = summary_stats(evaluations)

    parts: list[str] = []
    parts.append(f"<h1>{title}</h1>")
    parts.append(_warning_banner())
    parts.append(notes_instruction_banner())
    parts.append(
        f"<p><em>Last refreshed: {timestamp} by {_escape(refreshed_by)}</em></p>"
    )
    parts.append(_summary_section(stats))

    for role in ("pm", "eng", "design"):
        section = _role_section(role, filter_by_role(evaluations, role), notes)
        parts.append(section)

    parts.append(_ready_section(ready_to_advance(evaluations), notes))

    return title, "".join(parts)


# -----------------------------------------------------------------------------
# Section builders
# -----------------------------------------------------------------------------

def _warning_banner() -> str:
    return (
        '<div data-type="panel-warning">'
        "<p>⚠️ <strong>Bug data on this page is auto-generated.</strong> "
        "Edits to the bug rows themselves (titles, scores, missing fields) will be "
        "overwritten on the next refresh. Notes are preserved — see below."
        "</p></div>"
    )


def _summary_section(stats: dict[str, int]) -> str:
    return (
        "<h2>Summary</h2>"
        f"<p>📊 <strong>{stats['total']} bugs awaiting triage</strong></p>"
        "<ul>"
        f"<li>🔴 <strong>{stats['blocked']} fully blocked</strong> — 2+ fields missing</li>"
        f"<li>🟡 <strong>{stats['partial']} partially ready</strong> — 1 field missing</li>"
        f"<li>🟢 <strong>{stats['ready']} ready to advance</strong> — 0 fields missing</li>"
        "</ul>"
        "<p><strong>By role:</strong></p>"
        "<ul>"
        f"<li>PM holding: <strong>{stats['pm_holding']}</strong></li>"
        f"<li>Engineering holding: <strong>{stats['eng_holding']}</strong></li>"
        f"<li>Design holding: <strong>{stats['design_holding']}</strong></li>"
        "</ul>"
    )


def _role_section(
    role: str, evaluations: list[BugEvaluation], notes: dict[int, str]
) -> str:
    label = ROLE_LABELS[role]
    heading = f"<h2>🟡 Waiting on {label} ({len(evaluations)})</h2>"
    if not evaluations:
        return heading + "<p><em>No bugs blocked on this role.</em></p>"
    return heading + _bug_table(evaluations, role=role, notes=notes)


def _ready_section(
    evaluations: list[BugEvaluation], notes: dict[int, str]
) -> str:
    heading = f"<h2>✅ Ready to advance ({len(evaluations)})</h2>"
    if not evaluations:
        return heading + "<p><em>No bugs ready to advance.</em></p>"
    return heading + _bug_table(evaluations, role=None, notes=notes)


def _bug_table(
    evaluations: Iterable[BugEvaluation],
    role: str | None,
    notes: dict[int, str],
) -> str:
    rows = []
    show_missing = role is not None
    column_count = 9 if show_missing else 8

    header = (
        "<tr>"
        "<th>Bug</th>"
        "<th>Priority</th>"
        "<th>Score</th>"
        "<th>T-shirt Size</th>"
        "<th>Acceptance Criteria</th>"
        "<th>Owner</th>"
        "<th>Last Action</th>"
        "<th>Age</th>"
    )
    if show_missing:
        header += "<th>Missing</th>"
    header += "</tr>"

    for ev in evaluations:
        wi = ev.work_item
        title_cell = _title_cell(ev)
        priority = _priority_display(ev.priority)
        score = _score_display(wi.fields)
        tshirt = _tshirt_display(wi.fields)
        ac = _ac_preview(wi.fields)
        owner = _escape(wi.assigned_to or "—")
        last_action = _last_action_display(wi.changed_date)
        age = f"{ev.age_days}d"
        cells = (
            f"<td>{title_cell}</td>"
            f"<td>{priority}</td>"
            f"<td>{score}</td>"
            f"<td>{tshirt}</td>"
            f"<td>{ac}</td>"
            f"<td>{owner}</td>"
            f"<td>{last_action}</td>"
            f"<td>{age}</td>"
        )
        if show_missing:
            cells += f"<td>{_all_missing_display(ev)}</td>"
        rows.append(f"<tr>{cells}</tr>")
        # Per-bug notes row, preserved across refreshes
        rows.append(render_notes_row(wi.id, notes.get(wi.id), column_count))

    return f"<table><tbody>{header}{''.join(rows)}</tbody></table>"


# -----------------------------------------------------------------------------
# Cell formatters
# -----------------------------------------------------------------------------

def _title_cell(ev: BugEvaluation) -> str:
    """Combined bug ID + title link, with a Needs Design indicator beneath when applicable."""
    wi = ev.work_item
    label = f"#{wi.id} — {_escape(wi.title)}"
    link = f'<a href="{_escape(wi.url)}">{label}</a>'
    if ev.needs_design:
        return f'{link}<br/><strong>🎨 Needs Design</strong>'
    return link


def _priority_display(priority: str) -> str:
    """Render priority as a colored emoji + label.

    ADO priorities are 1 (must fix) to 4 (unimportant).
    """
    if not priority:
        return "—"
    emoji = PRIORITY_EMOJI.get(str(priority), "")
    return f"{emoji} P{priority}".strip()


def _score_display(fields: dict) -> str:
    """Render product score with the breakdown equation when available.

    Probability lives in Microsoft.VSTS.CMMI.Probability (the standard CMMI
    field), Impact in Custom.Impact, and the resulting Product Score in
    Custom.ProductScore. When all three are present, show the breakdown.

    Examples:
        Probability=3, Impact=3, Score=9  →  "9 (3 × 3)"
        Score=9 only                      →  "9"
        Probability=3, Impact=3 only      →  "3 × 3"
        nothing                           →  "—"
    """
    probability = fields.get("Microsoft.VSTS.CMMI.Probability")
    impact = fields.get("Custom.Impact")
    score = fields.get("Custom.ProductScore")

    has_score = score not in (None, "", 0, "0")
    has_parts = probability not in (None, "", 0, "0") and impact not in (None, "", 0, "0")

    if has_score and has_parts:
        return f"<strong>{score}</strong> ({probability} × {impact})"
    if has_score:
        return f"<strong>{score}</strong>"
    if has_parts:
        return f"({probability} × {impact})"
    return "—"


def _tshirt_display(fields: dict) -> str:
    """Render the T-shirt Size value, or em-dash if not set."""
    value = fields.get("Custom.TShirtSize")
    if not value:
        return "—"
    return _escape(str(value))


def _ac_preview(fields: dict) -> str:
    """Render an HTML-stripped preview of Acceptance Criteria."""
    raw = fields.get("Microsoft.VSTS.Common.AcceptanceCriteria") or ""
    if not raw:
        return "—"
    text = _strip_html(raw)
    if not text:
        return "—"
    if len(text) > AC_PREVIEW_CHARS:
        text = text[:AC_PREVIEW_CHARS].rstrip() + "…"
    return _escape(text)


def _last_action_display(changed_date: str) -> str:
    """Format the last-changed date as YYYY-MM-DD, or em-dash if missing/unparseable."""
    if not changed_date:
        return "—"
    try:
        dt = date_parser.isoparse(changed_date)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "—"


def _all_missing_display(ev: BugEvaluation) -> str:
    """Render every missing field on the bug, grouped by responsible role.

    Format:
        PM: Product Score, AC · Eng: T-shirt Size · Design: Design/Solution

    Only roles that actually have missing fields are shown. If nothing is
    missing (shouldn't happen in a role section but guard anyway), returns "—".
    """
    parts: list[str] = []
    for role in ("pm", "eng", "design"):
        missing = ev.missing_by_role.get(role) or []
        if not missing:
            continue
        label = ROLE_SHORT_LABELS[role]
        joined = ", ".join(_escape(m) for m in missing)
        parts.append(f"<strong>{label}:</strong> {joined}")
    if not parts:
        return "—"
    return " · ".join(parts)


def _strip_html(html: str) -> str:
    """Strip HTML tags and decode common entities for inline display."""
    if not html:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(
        r"</?(p|div|li|h[1-6]|tr|ul|ol)[^>]*>", "\n", text, flags=re.IGNORECASE
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _now_eastern_string() -> str:
    """Format current time in Eastern Time as a readable string."""
    try:
        from zoneinfo import ZoneInfo
        eastern = datetime.now(ZoneInfo("America/New_York"))
        return eastern.strftime("%Y-%m-%d %I:%M %p %Z")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _escape(s: str) -> str:
    """Minimal XHTML escaping for text content."""
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
