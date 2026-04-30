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

    total_steps = len(team_keys) * 2  # 2 queries per team
    step = 0

    for team_key in team_keys:
        team = TEAMS[team_key]
        team_result: dict[str, Any] = {
            "team": team["display_name"],
            "current": None,
            "historical": None,
            "errors": [],
        }

        for kind, page_id_key in (
            ("current", "current_page_id"),
            ("historical", "historical_page_id"),
        ):
            try:
                overall.markdown(
                    f"**{team['display_name']}** — {kind.capitalize()}: bothering Azure DevOps…"
                )
                step += 1
                progress_bar.progress(step / total_steps)

                wiql = wiql_for(team_key, kind)
                items = devops.fetch_by_wiql(wiql)

                overall.markdown(
                    f"**{team['display_name']}** — {kind.capitalize()}: counting what's missing on {len(items)} bug(s)…"
                )
                evaluations = evaluate_bugs(items)
                stats = summary_stats(evaluations)

                overall.markdown(
                    f"**{team['display_name']}** — {kind.capitalize()}: strong-arming Confluence…"
                )
                title, body = render_page(
                    team_display_name=team["display_name"],
                    page_kind=kind.capitalize(),
                    evaluations=evaluations,
                    refreshed_by=owner_name,
                )
                confluence.update_page(
                    page_id=team["confluence"][page_id_key],
                    title=title,
                    body_markdown=body,
                    version_message=f"Refreshed by {owner_name} via CP Bug Triage app",
                )
                team_result[kind] = stats
            except Exception as exc:
                team_result["errors"].append(f"{kind.capitalize()}: {exc}")
            time.sleep(0.1)
        results.append(team_result)

    progress_bar.progress(1.0)
    overall.empty()
    st.success("Done.")
    _render_results(results)


def _render_results(results: list[dict[str, Any]]):
    for r in results:
        st.markdown(f"### {r['team']}")
        if r["errors"]:
            for err in r["errors"]:
                st.error(err)
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
