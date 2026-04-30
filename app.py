"""CP Bug Triage — Streamlit app.

Workflow:
  1. User enters the shared app password.
  2. Picks themselves (Amy or Justina). Picker shows their portrait card.
  3. App shows the team(s) they own — one button per team plus a "Both" button.
  4. User clicks a team button → big red REFRESH button appears.
  5. Click → progress states → confirmation with stats and Confluence links.
"""

from __future__ import annotations

import time
from typing import Any

import streamlit as st

from config.teams import OWNERS, TEAMS, teams_for_owner, wiql_for
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
        for k in ("authenticated", "owner", "selected_team"):
            st.session_state.pop(k, None)
        st.rerun()


# =============================================================================
# Owner picker
# =============================================================================

def _render_owner_picker() -> str | None:
    """Show two owner cards. Return the selected owner key or None."""
    st.title("🐞 CP Bug Triage")
    st.write("Pick the legend who's running triage today.")
    st.write("")

    cols = st.columns(2)
    selected = st.session_state.get("owner")

    for col, key in zip(cols, ("amy", "justina")):
        owner = OWNERS[key]
        with col:
            try:
                st.image(owner["avatar_path"], use_container_width=True)
            except Exception:
                st.markdown(
                    "<div style='background:#F3F4F6;height:200px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:48px;'>👤</div>",
                    unsafe_allow_html=True,
                )
            st.markdown(f"### {owner['display_name']}")
            st.markdown(f"**{owner['title']}**")
            st.caption(owner["tagline"])
            if st.button(
                f"I'm {owner['display_name'].split()[0]}",
                key=f"pick_{key}",
                use_container_width=True,
                type="primary" if selected == key else "secondary",
            ):
                st.session_state["owner"] = key
                st.session_state.pop("selected_team", None)
                st.rerun()
    return selected


# =============================================================================
# Team picker
# =============================================================================

def _render_team_picker(owner_key: str):
    """Show buttons for each team this owner runs, plus Both."""
    owner = OWNERS[owner_key]
    teams = teams_for_owner(owner_key)
    team_keys = list(teams.keys())

    st.markdown(f"## Hey, {owner['display_name'].split()[0]}.")
    st.markdown("Which team are we refreshing?")
    st.write("")

    cols = st.columns(len(team_keys) + 1)
    for col, team_key in zip(cols[:-1], team_keys):
        team = teams[team_key]
        with col:
            if st.button(
                team["display_name"],
                key=f"team_{team_key}",
                use_container_width=True,
            ):
                st.session_state["selected_team"] = [team_key]
                st.rerun()
    with cols[-1]:
        if st.button("⚡ Both", key="team_both", use_container_width=True, type="primary"):
            st.session_state["selected_team"] = team_keys
            st.rerun()

    if st.button("← Switch person"):
        st.session_state.pop("owner", None)
        st.session_state.pop("selected_team", None)
        st.rerun()


# =============================================================================
# Refresh action
# =============================================================================

def _render_refresh_panel(team_keys: list[str]):
    team_names = ", ".join(TEAMS[k]["display_name"] for k in team_keys)
    st.markdown(f"## Refreshing: **{team_names}**")
    st.write("")

    if st.button("🚨  REFRESH  🚨", type="primary", use_container_width=True):
        _run_refresh(team_keys)

    st.write("")
    if st.button("← Back"):
        st.session_state.pop("selected_team", None)
        st.rerun()


def _run_refresh(team_keys: list[str]):
    """Execute the refresh for one or more teams. Show progress, then results."""
    owner_key = st.session_state.get("owner") or "unknown"
    owner_name = OWNERS.get(owner_key, {}).get("display_name", "Bug Triage app")

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

    # 4 phases per team (read, query, archive, update). Archive is shown as
    # a sub-step only when there are orphaned notes; the bar still counts it.
    total_steps = len(team_keys) * 4
    step = 0

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
            owner_name,
            devops,
            confluence,
            overall,
            lambda: _bump_progress(progress_bar, step, total_steps),
            team_result,
        )
        # Each team consumes 4 progress slots regardless
        step += 4
        progress_bar.progress(min(step / total_steps, 1.0))
        results.append(team_result)
        time.sleep(0.1)

    progress_bar.progress(1.0)
    overall.empty()
    st.success("Done.")
    _render_results(results)


def _bump_progress(bar, step, total):
    bar.progress(min(step / total, 1.0))


def _run_team_refresh(
    team_key: str,
    team: dict,
    owner_name: str,
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
                    version_message=(
                        f"Archived {len(entries)} note(s) by {owner_name}"
                    ),
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
                refreshed_by=owner_name,
                notes=notes_pool,
            )
            confluence.update_page(
                page_id=page_id,
                title=title,
                body_markdown=body,
                version_message=f"Refreshed by {owner_name} via CP Bug Triage app",
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

owner = st.session_state.get("owner")
selected_team = st.session_state.get("selected_team")

if not owner:
    _render_owner_picker()
elif not selected_team:
    _render_team_picker(owner)
else:
    _render_refresh_panel(selected_team)
