#!/usr/bin/env python3
"""Prediction Market News & Trends Dashboard.

Aggregates news from Polymarket, Kalshi, and regulatory sources into
a single-pane view with narrative trend detection.
"""

import time
from datetime import datetime, timezone

import streamlit as st

from news_fetcher import get_news, detect_narratives, detect_priority_alerts

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

items = get_news(force_refresh=force_refresh)

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

    import pandas as pd

    alert_rows = []
    for a in alerts:
        plat = a["platform"]
        if plat == "polymarket":
            plat_label = "Polymarket"
        elif plat == "kalshi":
            plat_label = "Kalshi"
        else:
            plat_label = "Both"
        alert_rows.append({
            "Platform": plat_label,
            "Category": ", ".join(a["categories"]),
            "Headline": a["title"],
            "Source": a["source_name"],
            "When": relative_time(a["published"]),
        })

    alert_df = pd.DataFrame(alert_rows)

    def highlight_alert_severity(row):
        """Red for security/outage, orange for regulatory, yellow for others."""
        cats = row["Category"].lower()
        if any(k in cats for k in ["security", "outage"]):
            return ["background-color: rgba(255, 60, 60, 0.2)"] * len(row)
        if "regulatory" in cats:
            return ["background-color: rgba(255, 140, 0, 0.2)"] * len(row)
        return ["background-color: rgba(255, 220, 80, 0.1)"] * len(row)

    styled_alerts = alert_df.style.apply(highlight_alert_severity, axis=1)
    st.dataframe(styled_alerts, use_container_width=True, hide_index=True)
    st.divider()

# =============================================================================
# NARRATIVE TRENDS TABLE
# =============================================================================

st.subheader("Narrative Trends")

df = detect_narratives(items)

if df.empty:
    st.info("No narrative trends detected yet.")
else:
    def highlight_cross_platform(row):
        """Highlight rows where both platforms have articles."""
        if row["Polymarket"] > 0 and row["Kalshi"] > 0:
            return ["background-color: rgba(255, 215, 0, 0.15)"] * len(row)
        return [""] * len(row)

    styled = (
        df.style
        .apply(highlight_cross_platform, axis=1)
        .format({"Polymarket": "{:.0f}", "Kalshi": "{:.0f}", "Total": "{:.0f}"})
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

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
