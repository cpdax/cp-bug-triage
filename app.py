"""CP Bug Triage — Streamlit app.

Workflow:
  1. User enters the shared app password.
  2. Single screen: checkboxes for the 4 CP team spaces + a refresh button.
  3. Click → progress states → confirmation with stats and Confluence links.

Anyone with the password can refresh any combination of spaces. Owner labels
next to each checkbox are hint text only.
"""

from __future__ import annotations

import time
from typing import Any

import streamlit as st

from config.teams import TEAMS, wiql_for
from lib.confluence import ConfluenceClient
from lib.devops import DevOpsClient
from lib.notes import (
    archive_entry_html,
    extract_notes,
    prepend_archive_entries,
    today_iso_date,
)
from lib.renderer import render_page
from lib.triage import evaluate_bugs, summary_stats


# =============================================================================
# Page setup
# =============================================================================

st.set_page_config(
    page_title="CP Bug Triage",
    page_icon="🐞",
    layout="centered",
    initial_sidebar_state="collapsed",
)


# =============================================================================
# Password gate
# =============================================================================

def _check_password() -> bool:
    """Return True if the user has entered the correct shared password."""

    def _on_password_change():
        entered = st.session_state.get("password_input", "")
        if entered == st.secrets["access"]["password"]:
            st.session_state["authenticated"] = True
            st.session_state["password_input"] = ""
        else:
            st.session_state["authenticated"] = False

    if st.session_state.get("authenticated"):
        return True

    st.title("🐞 CP Bug Triage")
    st.write("Enter the app password to continue. Get it from Dax Collins.")
    st.text_input(
        "Password",
        type="password",
        on_change=_on_password_change,
        key="password_input",
    )
    if st.session_state.get("authenticated") is False:
        st.error("😕 Password incorrect.")
    st.stop()


_check_password()


# =============================================================================
# Sidebar
# =============================================================================

with st.sidebar:
    st.markdown("**🐞 CP Bug Triage**")
    st.caption("Owned by Product Operations · contact Dax Collins")
    st.divider()
    if st.button("Sign out"):
        for k in list(st.session_state.keys()):
            if k.startswith(("cb_", "authenticated", "password_input")):
                st.session_state.pop(k, None)
        st.rerun()


# =============================================================================
# Main screen — team checkboxes + refresh button
# =============================================================================

def _render_main_screen():
    st.title("🐞 CP Bug Triage")
    st.markdown("Check the spaces you want to refresh, then hit the button.")
    st.write("")

    # Quick-select helpers
    helper_cols = st.columns([1, 1, 4])
    with helper_cols[0]:
        if st.button("Select all", use_container_width=True):
            for team_key in TEAMS:
                st.session_state[f"cb_{team_key}"] = True
            st.rerun()
    with helper_cols[1]:
        if st.button("Clear all", use_container_width=True):
            for team_key in TEAMS:
                st.session_state[f"cb_{team_key}"] = False
            st.rerun()

    st.write("")

    # Checkboxes
    selected: list[str] = []
    for team_key, team in TEAMS.items():
        label = f"{team['display_name']} · *{team['owner_label']}*"
        # Streamlit checkbox state persists in session via the key
        is_checked = st.checkbox(
            label,
            key=f"cb_{team_key}",
        )
        if is_checked:
            selected.append(team_key)

    st.write("")

    # Big red refresh button — disabled when nothing selected
    refresh_clicked = st.button(
        "🚨  REFRESH  🚨",
        type="primary",
        use_container_width=True,
        disabled=not selected,
    )
    if not selected:
        st.caption("Select at least one space to enable refresh.")

    if refresh_clicked and selected:
        _run_refresh(selected)


# =============================================================================
# Refresh execution
# =============================================================================

def _run_refresh(team_keys: list[str]):
    """Execute the refresh for one or more teams. Show progress, then results."""
    devops = DevOpsClient(
        org_url=st.secrets["devops"]["org_url"],
        project=st.secrets["devops"]["project"],
        pat=st.secrets["devops"]["pat"],
    )
    confluence = ConfluenceClient(
        base_url=st.secrets["confluence"]["base_url"],
        email=st.secrets["confluence"]["email"],
        api_token=st.secrets["confluence"]["api_token"],
    )

    results: list[dict[str, Any]] = []
    overall = st.empty()
    progress_bar = st.progress(0)

    # 4 phases per team (read, query, archive, update). Bar advances by 4 per team.
    total_steps = len(team_keys) * 4
    step_counter = {"step": 0}

    for team_key in team_keys:
        team = TEAMS[team_key]
        team_result: dict[str, Any] = {
            "team": team["display_name"],
            "current": None,
            "historical": None,
            "archived_count": 0,
            "errors": [],
        }
        _run_team_refresh(
            team_key,
            team,
            devops,
            confluence,
            overall,
            lambda: _bump_progress(progress_bar, step_counter, total_steps),
            team_result,
        )
        results.append(team_result)
        time.sleep(0.1)

    progress_bar.progress(1.0)
    overall.empty()
    st.success("Done.")
    _render_results(results)


def _bump_progress(bar, counter, total):
    counter["step"] += 1
    bar.progress(min(counter["step"] / total, 1.0))


def _run_team_refresh(
    team_key: str,
    team: dict,
    devops: DevOpsClient,
    confluence: ConfluenceClient,
    overall_slot,
    bump,
    team_result: dict[str, Any],
):
    """Refresh both Current and Historical pages for one team, with note archiving."""
    team_name = team["display_name"]
    current_page_id = team["confluence"]["current_page_id"]
    historical_page_id = team["confluence"]["historical_page_id"]
    archive_page_id = team["confluence"]["archive_page_id"]

    # ---- Phase 1: Read existing notes from both pages -----------------------
    overall_slot.markdown(f"**{team_name}** · reading existing notes…")
    bump()
    current_html = ""
    historical_html = ""
    try:
        current_html = confluence.fetch_page_storage(current_page_id)
    except Exception:
        current_html = ""
    try:
        historical_html = confluence.fetch_page_storage(historical_page_id)
    except Exception:
        historical_html = ""
    # Current's notes win on conflict (most recent edit assumed to be there).
    notes_pool: dict[int, str] = {
        **extract_notes(historical_html),
        **extract_notes(current_html),
    }

    # ---- Phase 2: Query DevOps for both kinds -------------------------------
    overall_slot.markdown(f"**{team_name}** · bothering Azure DevOps…")
    bump()
    current_items = []
    historical_items = []
    try:
        current_items = devops.fetch_by_wiql(wiql_for(team_key, "current"))
    except Exception as exc:
        team_result["errors"].append(f"DevOps query (Current): {exc}")
    try:
        historical_items = devops.fetch_by_wiql(wiql_for(team_key, "historical"))
    except Exception as exc:
        team_result["errors"].append(f"DevOps query (Historical): {exc}")

    # If both queries failed, bail without archiving — we'd otherwise wipe
    # every note as "orphaned" since the active set looks empty.
    if not current_items and not historical_items and team_result["errors"]:
        return

    all_active_ids: set[int] = {item.id for item in current_items} | {
        item.id for item in historical_items
    }

    # ---- Phase 3: Archive orphaned notes -----------------------------------
    orphan_ids = [bid for bid in notes_pool.keys() if bid not in all_active_ids]
    if orphan_ids:
        overall_slot.markdown(
            f"**{team_name}** · archiving {len(orphan_ids)} closed-bug note(s)…"
        )
    bump()
    if orphan_ids:
        try:
            titles = devops.fetch_titles(orphan_ids)
            today = today_iso_date()
            entries = []
            for bid in orphan_ids:
                meta = titles.get(bid, {})
                entries.append(
                    archive_entry_html(
                        bug_id=bid,
                        bug_title=meta.get("title", ""),
                        bug_url=meta.get(
                            "url",
                            f"{devops.org_url}/{devops.project}/_workitems/edit/{bid}",
                        ),
                        note_text=notes_pool[bid],
                        archived_date=today,
                    )
                )

            existing_archive_html = ""
            try:
                existing_archive_html = confluence.fetch_page_storage(archive_page_id)
            except Exception as exc:
                team_result["errors"].append(f"Archive read: {exc}")

            updated_archive_html = prepend_archive_entries(
                existing_archive_html, entries
            )
            if updated_archive_html and updated_archive_html != existing_archive_html:
                confluence.update_page(
                    page_id=archive_page_id,
                    title=f"Closed Bug Notes — {team_name}",
                    body_markdown=updated_archive_html,
                    version_message=f"Archived {len(entries)} note(s)",
                )
                team_result["archived_count"] = len(entries)
        except Exception as exc:
            team_result["errors"].append(f"Archive write: {exc}")

    # ---- Phase 4: Render and update both active pages -----------------------
    overall_slot.markdown(f"**{team_name}** · strong-arming Confluence…")
    bump()
    for kind, items, page_id in (
        ("current", current_items, current_page_id),
        ("historical", historical_items, historical_page_id),
    ):
        if not items and any(
            err.startswith(f"DevOps query ({kind.capitalize()})")
            for err in team_result["errors"]
        ):
            continue  # query failed earlier, don't blank the page
        try:
            evaluations = evaluate_bugs(items)
            stats = summary_stats(evaluations)
            title, body = render_page(
                team_display_name=team_name,
                page_kind=kind.capitalize(),
                evaluations=evaluations,
                notes=notes_pool,
            )
            confluence.update_page(
                page_id=page_id,
                title=title,
                body_markdown=body,
                version_message="Refreshed via CP Bug Triage app",
            )
            team_result[kind] = stats
        except Exception as exc:
            team_result["errors"].append(f"{kind.capitalize()} update: {exc}")


def _render_results(results: list[dict[str, Any]]):
    for r in results:
        st.markdown(f"### {r['team']}")
        if r["errors"]:
            for err in r["errors"]:
                st.error(err)
        if r.get("archived_count"):
            st.info(
                f"📦 Archived {r['archived_count']} note(s) for closed bugs."
            )
        if r["current"]:
            _render_stats_block("Current Bugs", r["current"])
        if r["historical"]:
            _render_stats_block("Historical Bugs", r["historical"])
        st.divider()


def _render_stats_block(label: str, stats: dict[str, int]):
    cols = st.columns(4)
    cols[0].metric(f"{label} — Total", stats["total"])
    cols[1].metric("🔴 Blocked", stats["blocked"])
    cols[2].metric("🟡 Partial", stats["partial"])
    cols[3].metric("🟢 Ready", stats["ready"])
    st.caption(
        f"By role: PM {stats['pm_holding']} · Eng {stats['eng_holding']} · Design {stats['design_holding']}"
    )


# =============================================================================
# Main flow
# =============================================================================

_render_main_screen()
