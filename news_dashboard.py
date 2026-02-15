#!/usr/bin/env python3
"""Prediction Market News & Trends Dashboard.

Aggregates news from Polymarket, Kalshi, and regulatory sources into
a single-pane view with narrative trend detection.
"""

import time
from datetime import datetime, timezone

import streamlit as st

from news_fetcher import get_news, detect_narratives, detect_narratives_with_articles, detect_priority_alerts

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
