#!/usr/bin/env python3
"""Prediction Market News & Trends Dashboard.

Aggregates news from Polymarket, Kalshi, and regulatory sources into
a single-pane view with narrative trend detection.
"""

import time
from datetime import datetime, timezone

import streamlit as st

from news_fetcher import get_news, detect_narratives, detect_narratives_with_articles, detect_priority_alerts
from platform_monitor import get_health_status

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title="Prediction Market News",
    page_icon="📰",
    layout="wide",
)

# =============================================================================
# HELPERS
# =============================================================================

def relative_time(iso_str: str) -> str:
    """Convert ISO 8601 timestamp to relative time string."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt

        seconds = int(diff.total_seconds())
        if seconds < 0:
            return "just now"
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 30:
            return f"{days}d ago"
        months = days // 30
        return f"{months}mo ago"
    except Exception:
        return ""


def platform_badge(platform: str) -> str:
    """Return a colored badge string for the platform."""
    if platform == "polymarket":
        return ":violet[PM]"
    elif platform == "kalshi":
        return ":blue[KA]"
    else:
        return ":gray[ALL]"


# =============================================================================
# SIDEBAR
# =============================================================================

with st.sidebar:
    st.title("Filters")

    platform_filter = st.radio(
        "Platform",
        ["All", "Polymarket", "Kalshi"],
        index=0,
    )

    source_filter = st.radio(
        "Source",
        ["All", "Blog", "Google News", "Twitter"],
        index=0,
    )

    max_items = st.slider("Max items", min_value=10, max_value=200, value=50, step=10)

    st.divider()

    force_refresh = st.button("Refresh Now")
    auto_refresh = st.checkbox("Auto-refresh (every 5 min)", value=True)


# =============================================================================
# LOAD DATA
# =============================================================================

items, source_status = get_news(force_refresh=force_refresh)
health = get_health_status(force_refresh=force_refresh)

# =============================================================================
# SOURCE STATUS (rendered in sidebar after data loads)
# =============================================================================

with st.sidebar:
    st.divider()
    st.subheader("Source Status")

    # Fixed order: always show these three
    for src_name in ["Polymarket Blog", "Google News", "X / Twitter"]:
        info = source_status.get(src_name, {})
        active = info.get("active", False)
        count = info.get("count", 0)
        error = info.get("error")

        if active:
            st.markdown(
                f'<div style="padding:4px 0;"><span style="color:#2ea043; font-size:18px;">&#9679;</span> '
                f'<b>{src_name}</b> &mdash; {count} articles</div>',
                unsafe_allow_html=True,
            )
        elif error:
            st.markdown(
                f'<div style="padding:4px 0;"><span style="color:#f85149; font-size:18px;">&#9679;</span> '
                f'<b>{src_name}</b> &mdash; inactive</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"  {error}")
        else:
            st.markdown(
                f'<div style="padding:4px 0;"><span style="color:#848d97; font-size:18px;">&#9679;</span> '
                f'<b>{src_name}</b> &mdash; 0 articles</div>',
                unsafe_allow_html=True,
            )

# -------------------------------------------------------------------------
# Platform Health (sidebar)
# -------------------------------------------------------------------------

with st.sidebar:
    st.divider()
    st.subheader("Platform Health")

    _status_color = {"UP": "#2ea043", "SLOW": "#d29922", "DEGRADED": "#d29922", "DOWN": "#f85149"}

    for ep in health.get("endpoints", []):
        color = _status_color.get(ep["status"], "#848d97")
        latency_str = f'{ep["latency_ms"]}ms' if ep["latency_ms"] is not None else "—"
        schema_icon = ""
        if ep["schema_ok"] is False:
            schema_icon = ' <span style="color:#f85149;" title="Schema drift">&#9888;</span>'
        st.markdown(
            f'<div style="padding:2px 0;"><span style="color:{color}; font-size:18px;">&#9679;</span> '
            f'<b>{ep["name"]}</b> &mdash; {ep["status"]} ({latency_str}){schema_icon}</div>',
            unsafe_allow_html=True,
        )

    # SDK info
    sdk = health.get("sdk_version", {})
    if sdk.get("latest_version"):
        pinned = sdk.get("pinned_version", "?")
        latest = sdk["latest_version"]
        if sdk.get("is_major_bump"):
            sdk_color = "#f85149"
            sdk_label = "Major version bump!"
        elif sdk.get("is_minor_bump"):
            sdk_color = "#d29922"
            sdk_label = "Minor version bump available"
        elif sdk.get("update_available"):
            sdk_color = "#848d97"
            sdk_label = "Patch available"
        else:
            sdk_color = "#2ea043"
            sdk_label = "Up to date"
        st.markdown(
            f'<div style="padding:4px 0; font-size:13px;"><b>SDK:</b> py-clob-client<br>'
            f'&nbsp;&nbsp;Pinned: >={pinned} &rarr; Latest: {latest}<br>'
            f'&nbsp;&nbsp;<span style="color:{sdk_color};">{sdk_label}</span></div>',
            unsafe_allow_html=True,
        )

# Apply platform filter
if platform_filter == "Polymarket":
    filtered = [i for i in items if i["platform"] in ("polymarket", "both")]
elif platform_filter == "Kalshi":
    filtered = [i for i in items if i["platform"] in ("kalshi", "both")]
else:
    filtered = items

# Apply source filter
if source_filter == "Blog":
    filtered = [i for i in filtered if "Blog" in i["source_name"]]
elif source_filter == "Google News":
    filtered = [i for i in filtered if "Google News" in i["source_name"]]
elif source_filter == "Twitter":
    filtered = [i for i in filtered if "Twitter" in i["source_name"]]

# Limit
filtered = filtered[:max_items]


# =============================================================================
# MAIN AREA
# =============================================================================

st.title("Prediction Market News & Trends")
st.caption(f"Articles: {len(filtered)} (of {len(items)} total)")

# =============================================================================
# PLATFORM HEALTH SECTION (main area)
# =============================================================================

_overall = health.get("overall_status", "HEALTHY")
_checked_at = health.get("checked_at", "")
_banner_colors = {
    "HEALTHY": ("rgba(46, 160, 67, 0.15)", "#2ea043", "All Systems Healthy"),
    "WARNING": ("rgba(210, 153, 34, 0.15)", "#d29922", "Warning"),
    "CRITICAL": ("rgba(248, 81, 73, 0.15)", "#f85149", "Critical"),
}
_bg, _fg, _label = _banner_colors.get(_overall, _banner_colors["HEALTHY"])

# Parse relative time for checked_at
_checked_ago = ""
if _checked_at:
    _checked_ago = relative_time(_checked_at)

# Decide if we need the full section (always show banner, detail only when non-healthy or has issues)
_has_schema_drift = any(ep.get("schema_ok") is False for ep in health.get("endpoints", []))
_has_fee_values = any(v not in (None, 0) for v in health.get("fee_status", {}).values())
_sdk = health.get("sdk_version", {})
_has_sdk_update = _sdk.get("update_available", False)
_show_detail = _overall != "HEALTHY" or _has_schema_drift or _has_fee_values or _has_sdk_update

st.markdown(
    f'<div style="background:{_bg}; border-left:4px solid {_fg}; padding:10px 16px; '
    f'border-radius:4px; margin-bottom:12px;">'
    f'<span style="color:{_fg}; font-weight:bold; font-size:16px;">{_label}</span>'
    f'<span style="color:#848d97; float:right; font-size:13px;">Last checked: {_checked_ago}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

if _show_detail:
    # API Health table
    _health_rows = ""
    for ep in health.get("endpoints", []):
        s_color = {"UP": "#2ea043", "SLOW": "#d29922", "DEGRADED": "#d29922", "DOWN": "#f85149"}.get(ep["status"], "#848d97")
        latency_str = f'{ep["latency_ms"]}ms' if ep["latency_ms"] is not None else "—"
        schema_str = '<span style="color:#2ea043;">&#10003;</span>' if ep.get("schema_ok") else (
            '<span style="color:#f85149;">&#10007;</span>' if ep.get("schema_ok") is False else "—"
        )

        # Details column
        details = []
        if ep["name"] == "CLOB API" and ep.get("field_changes"):
            fees = ep["field_changes"]
            parts = [f"{k}={v}" for k, v in fees.items()]
            details.append(f"Fees: {', '.join(parts)}")
        if ep["name"] == "Exchange Status" and ep.get("extra_info"):
            info = ep["extra_info"]
            trading = "Active" if info.get("trading_active") else "Inactive"
            details.append(f"Trading: {trading}")
        if ep.get("error"):
            details.append(f'<span style="color:#f85149;">{ep["error"]}</span>')
        details_str = "; ".join(details) if details else ""

        _health_rows += f"""<tr style="border-bottom:1px solid #333;">
            <td style="padding:6px;">{ep['platform']}</td>
            <td style="padding:6px;">{ep['name']}</td>
            <td style="padding:6px;"><span style="color:{s_color}; font-weight:bold;">{ep['status']}</span></td>
            <td style="padding:6px;">{latency_str}</td>
            <td style="padding:6px;">{schema_str}</td>
            <td style="padding:6px; font-size:12px;">{details_str}</td>
        </tr>"""

    st.markdown(
        f"""<table style="width:100%; border-collapse:collapse; font-size:14px;">
        <tr style="border-bottom:2px solid #444; text-align:left;">
            <th style="padding:8px 6px; width:100px;">Platform</th>
            <th style="padding:8px 6px; width:140px;">Endpoint</th>
            <th style="padding:8px 6px; width:80px;">Status</th>
            <th style="padding:8px 6px; width:80px;">Latency</th>
            <th style="padding:8px 6px; width:70px;">Schema</th>
            <th style="padding:8px 6px;">Details</th>
        </tr>
        {_health_rows}
        </table>""",
        unsafe_allow_html=True,
    )

    # Schema Drift Alerts
    _drift_eps = [ep for ep in health.get("endpoints", []) if ep.get("schema_ok") is False]
    if _drift_eps:
        for ep in _drift_eps:
            missing = ", ".join(ep.get("missing_keys", []))
            st.markdown(
                f'<div style="background:rgba(248, 81, 73, 0.1); border-left:3px solid #f85149; '
                f'padding:8px 12px; margin:6px 0; border-radius:3px; font-size:13px;">'
                f'<b>Schema Drift:</b> {ep["platform"]} {ep["name"]} &mdash; '
                f'missing fields: <code>{missing}</code></div>',
                unsafe_allow_html=True,
            )

    # Fee Monitor
    _fees = health.get("fee_status", {})
    if _has_fee_values:
        fee_parts = [f"<b>{k}</b>: {v}" for k, v in _fees.items()]
        st.markdown(
            f'<div style="background:rgba(210, 153, 34, 0.1); border-left:3px solid #d29922; '
            f'padding:8px 12px; margin:6px 0; border-radius:3px; font-size:13px;">'
            f'<b>Fee Change Detected:</b> CLOB API &mdash; {", ".join(fee_parts)}</div>',
            unsafe_allow_html=True,
        )

    # SDK Version
    if _has_sdk_update:
        pinned = _sdk.get("pinned_version", "?")
        latest = _sdk.get("latest_version", "?")
        pypi_url = _sdk.get("pypi_url", "")
        if _sdk.get("is_major_bump"):
            sdk_bg = "rgba(248, 81, 73, 0.1)"
            sdk_border = "#f85149"
            sdk_level = "Major version bump"
        elif _sdk.get("is_minor_bump"):
            sdk_bg = "rgba(210, 153, 34, 0.1)"
            sdk_border = "#d29922"
            sdk_level = "Minor version bump"
        else:
            sdk_bg = "rgba(134, 141, 151, 0.1)"
            sdk_border = "#848d97"
            sdk_level = "Patch available"

        gh = health.get("github_releases", {})
        gh_url = gh.get("latest_release_url", "")
        links = f'<a href="{pypi_url}" target="_blank" style="color:#58a6ff;">PyPI</a>'
        if gh_url:
            links += f' | <a href="{gh_url}" target="_blank" style="color:#58a6ff;">GitHub</a>'

        st.markdown(
            f'<div style="background:{sdk_bg}; border-left:3px solid {sdk_border}; '
            f'padding:8px 12px; margin:6px 0; border-radius:3px; font-size:13px;">'
            f'<b>{sdk_level}:</b> py-clob-client &mdash; '
            f'pinned >={pinned} &rarr; latest {latest} &mdash; {links}</div>',
            unsafe_allow_html=True,
        )

    st.divider()

# =============================================================================
# PRIORITY ALERTS - Platform structural / service changes
# =============================================================================

alerts = detect_priority_alerts(items)

if alerts:
    st.subheader(f"Priority Alerts ({len(alerts)})")

    def _severity_color(cats_str: str) -> str:
        cats = cats_str.lower()
        if any(k in cats for k in ["security", "outage"]):
            return "rgba(255, 60, 60, 0.2)"
        if "regulatory" in cats:
            return "rgba(255, 140, 0, 0.2)"
        return "rgba(255, 220, 80, 0.1)"

    def _plat_label(plat: str) -> str:
        if plat == "polymarket":
            return "Polymarket"
        if plat == "kalshi":
            return "Kalshi"
        return "Both"

    # Build HTML table with clickable links - no truncation
    table_html = """<table style="width:100%; border-collapse:collapse; font-size:14px; table-layout:fixed;">
    <colgroup>
        <col style="width:90px;">
        <col style="width:160px;">
        <col>
        <col style="width:150px;">
        <col style="width:70px;">
    </colgroup>
    <tr style="border-bottom:2px solid #444; text-align:left;">
        <th style="padding:8px 6px;">Platform</th>
        <th style="padding:8px 6px;">Category</th>
        <th style="padding:8px 6px;">Headline</th>
        <th style="padding:8px 6px;">Source</th>
        <th style="padding:8px 6px;">When</th>
    </tr>"""

    for a in alerts:
        cats = ", ".join(a["categories"])
        bg = _severity_color(cats)
        link = a["link"]
        title = a["title"].replace('"', '&quot;')
        table_html += f"""<tr style="background-color:{bg}; border-bottom:1px solid #333;">
        <td style="padding:6px; white-space:nowrap;">{_plat_label(a['platform'])}</td>
        <td style="padding:6px; word-wrap:break-word; overflow-wrap:break-word;">{cats}</td>
        <td style="padding:6px; word-wrap:break-word; overflow-wrap:break-word;"><a href="{link}" target="_blank" style="color:#58a6ff; text-decoration:none;">{title}</a></td>
        <td style="padding:6px; word-wrap:break-word; overflow-wrap:break-word;">{a['source_name']}</td>
        <td style="padding:6px; white-space:nowrap;">{relative_time(a['published'])}</td>
    </tr>"""

    table_html += "</table>"
    st.markdown(table_html, unsafe_allow_html=True)
    st.divider()

# =============================================================================
# NARRATIVE TRENDS TABLE
# =============================================================================

st.subheader("Narrative Trends")

df = detect_narratives(items)
narrative_articles = detect_narratives_with_articles(items)

if df.empty:
    st.info("No narrative trends detected yet.")
else:
    for _, row in df.iterrows():
        narrative = row["Narrative"]
        pm_count = int(row["Polymarket"])
        ka_count = int(row["Kalshi"])
        total = int(row["Total"])
        cross = pm_count > 0 and ka_count > 0
        highlight = " style=\"background-color: rgba(255, 215, 0, 0.15);\"" if cross else ""

        with st.expander(f"**{narrative}** — PM: {pm_count} | Kalshi: {ka_count} | Total: {total}" + (" (cross-platform)" if cross else "")):
            arts = narrative_articles.get(narrative, [])
            if arts:
                rows_html = ""
                for art in arts:
                    plat = art["platform"]
                    if plat == "polymarket":
                        plat_label = "Polymarket"
                    elif plat == "kalshi":
                        plat_label = "Kalshi"
                    else:
                        plat_label = "Both"
                    title_safe = art["title"].replace('"', '&quot;')
                    rows_html += f"""<tr>
                        <td style="padding:4px 6px;">{plat_label}</td>
                        <td style="padding:4px 6px;"><a href="{art['link']}" target="_blank" style="color:#58a6ff; text-decoration:none;">{title_safe}</a></td>
                        <td style="padding:4px 6px;">{art['source_name']}</td>
                        <td style="padding:4px 6px;">{relative_time(art['published'])}</td>
                    </tr>"""

                st.markdown(f"""<table style="width:100%; border-collapse:collapse; font-size:13px;">
                    <tr style="border-bottom:1px solid #444; text-align:left;">
                        <th style="padding:4px 6px; min-width:90px;">Platform</th>
                        <th style="padding:4px 6px;">Article</th>
                        <th style="padding:4px 6px; min-width:140px;">Source</th>
                        <th style="padding:4px 6px; min-width:70px;">When</th>
                    </tr>
                    {rows_html}
                </table>""", unsafe_allow_html=True)
            else:
                st.write("No articles found.")

st.divider()

# =============================================================================
# NEWS FEED
# =============================================================================

if not filtered:
    st.info("No articles found. Try adjusting filters or click Refresh.")
else:
    for item in filtered:
        badge = platform_badge(item["platform"])
        ago = relative_time(item["published"])

        st.markdown(f"**{badge} [{item['title']}]({item['link']})**")
        st.caption(f"{item['source_name']} | {ago}")
        if item.get("summary"):
            st.markdown(f"<small>{item['summary']}</small>", unsafe_allow_html=True)
        st.divider()

# =============================================================================
# AUTO-REFRESH
# =============================================================================

if auto_refresh:
    time.sleep(300)
    st.rerun()
