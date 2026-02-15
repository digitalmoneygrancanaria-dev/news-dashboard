"""Prediction Market News - Fetching, parsing, caching, and narrative detection.

Aggregates news from multiple sources for Polymarket and Kalshi platforms.
"""

import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import pandas as pd
import requests

# =============================================================================
# CONSTANTS
# =============================================================================

CACHE_FILE = Path(__file__).parent / "news_cache.json"
CACHE_TTL_SECONDS = 600  # 10 minutes

RSS_SOURCES = [
    {
        "url": "https://news.polymarket.com/feed",
        "platform": "polymarket",
        "source_name": "Polymarket Blog",
    },
]

GOOGLE_NEWS_QUERIES = [
    {
        "query": "Polymarket",
        "platform": "polymarket",
        "source_name": "Google News: Polymarket",
    },
    {
        "query": "Kalshi",
        "platform": "kalshi",
        "source_name": "Google News: Kalshi",
    },
    {
        "query": "prediction market regulation",
        "platform": "both",
        "source_name": "Google News: Regulation",
    },
]

PRIORITY_KEYWORDS = {
    "API Change": ["api change", "api update", "new api", "api v2", "api v3", "deprecat", "endpoint", "breaking change", "migration guide"],
    "Outage / Downtime": ["outage", "downtime", "incident", "service disruption", "degraded", "maintenance", "status page", "unavailable"],
    "Regulatory Action": ["cftc order", "sec action", "cease and desist", "enforcement", "fine", "penalty", "banned", "prohibited", "injunction", "lawsuit"],
    "Fee / Structure Change": ["fee change", "fee structure", "new fees", "commission", "pricing change", "cost change", "withdrawal fee", "deposit fee"],
    "Platform Update": ["platform update", "new feature", "redesign", "ui change", "app update", "version release", "rollout"],
    "Market Structure": ["market structure", "order type", "limit order", "market order", "liquidity change", "matching engine", "settlement change", "resolution change"],
    "Partnership / Integration": ["partnership", "integration", "acquired", "acquisition", "merger", "collaboration", "onboard"],
    "Security": ["hack", "breach", "exploit", "vulnerability", "security incident", "unauthorized", "compromised", "leaked"],
}

NARRATIVE_KEYWORDS = {
    "Crypto / Bitcoin": ["crypto", "bitcoin", "btc", "ethereum", "defi"],
    "Arbitrage / Bots": ["arbitrage", "bot", "automated", "algo", "trading"],
    "Regulation / CFTC": ["regulation", "cftc", "sec", "compliance", "legal", "ruling", "ban"],
    "API / Technical": ["api", "outage", "downtime", "bug", "update", "migration", "v2"],
    "New Markets": ["new market", "launch", "listing", "added"],
    "Elections / Politics": ["election", "vote", "poll", "trump", "biden", "congress"],
    "Sports": ["nba", "nfl", "mlb", "ufc", "soccer", "super bowl"],
    "Volume / Growth": ["volume", "tvl", "growth", "record", "milestone", "users"],
}


# =============================================================================
# HELPERS
# =============================================================================

def _make_id(title: str, link: str) -> str:
    """Generate a deterministic dedup ID from title+link."""
    raw = f"{title}|{link}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _parse_date(entry) -> str:
    """Parse feed entry date to ISO 8601 UTC string."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            pass
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, max_len: int = 300) -> str:
    """Truncate text to max_len chars."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


# =============================================================================
# FEED PARSING
# =============================================================================

def _parse_feed(url: str, platform: str, source_name: str) -> list[dict]:
    """Parse a single RSS/Atom feed URL into normalized news items."""
    try:
        feed = feedparser.parse(url)
    except Exception as e:
        print(f"[news_fetcher] Error parsing {url}: {e}")
        return []

    items = []
    for entry in feed.entries:
        title = _strip_html(getattr(entry, "title", ""))
        link = getattr(entry, "link", "")
        if not title or not link:
            continue

        summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
        summary = _truncate(_strip_html(summary_raw))
        author = getattr(entry, "author", None)

        items.append({
            "id": _make_id(title, link),
            "title": title,
            "link": link,
            "published": _parse_date(entry),
            "source_name": source_name,
            "platform": platform,
            "summary": summary,
            "author": author,
        })

    return items


def fetch_rss_sources(status: dict) -> list[dict]:
    """Fetch all configured RSS sources (Polymarket Substack)."""
    all_items = []
    for src in RSS_SOURCES:
        try:
            items = _parse_feed(src["url"], src["platform"], src["source_name"])
            all_items.extend(items)
            status["Polymarket Blog"] = {"active": len(items) > 0, "count": len(items), "error": None}
        except Exception as e:
            status["Polymarket Blog"] = {"active": False, "count": 0, "error": str(e)}
    return all_items


def fetch_google_news(status: dict) -> list[dict]:
    """Fetch Google News RSS for each configured query."""
    all_items = []
    total = 0
    errors = []
    for q in GOOGLE_NEWS_QUERIES:
        query_encoded = q["query"].replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={query_encoded}&hl=en-US&gl=US&ceid=US:en"
        try:
            items = _parse_feed(url, q["platform"], q["source_name"])
            all_items.extend(items)
            total += len(items)
        except Exception as e:
            errors.append(str(e))
    status["Google News"] = {
        "active": total > 0,
        "count": total,
        "error": "; ".join(errors) if errors else None,
    }
    return all_items


def fetch_twitter(status: dict) -> list[dict]:
    """Fetch recent tweets from @Polymarket and @Kalshi via X API v2.

    Gracefully returns empty list if TWITTER_BEARER_TOKEN is not set.
    """
    bearer_token = os.environ.get("TWITTER_BEARER_TOKEN")
    if not bearer_token:
        status["X / Twitter"] = {"active": False, "count": 0, "error": "No TWITTER_BEARER_TOKEN configured"}
        return []

    accounts = [
        {"username": "Polymarket", "platform": "polymarket", "source_name": "Twitter: @Polymarket"},
        {"username": "Kalshi", "platform": "kalshi", "source_name": "Twitter: @Kalshi"},
    ]

    headers = {"Authorization": f"Bearer {bearer_token}"}
    all_items = []
    errors = []

    for acct in accounts:
        try:
            # Get user ID
            user_resp = requests.get(
                f"https://api.twitter.com/2/users/by/username/{acct['username']}",
                headers=headers,
                timeout=10,
            )
            if user_resp.status_code != 200:
                errors.append(f"{acct['username']}: HTTP {user_resp.status_code}")
                continue
            user_id = user_resp.json()["data"]["id"]

            # Get recent tweets
            tweets_resp = requests.get(
                f"https://api.twitter.com/2/users/{user_id}/tweets",
                headers=headers,
                params={
                    "max_results": 20,
                    "tweet.fields": "created_at,text,author_id",
                    "exclude": "retweets,replies",
                },
                timeout=10,
            )
            if tweets_resp.status_code != 200:
                errors.append(f"{acct['username']} tweets: HTTP {tweets_resp.status_code}")
                continue

            data = tweets_resp.json().get("data", [])
            for tweet in data:
                title = _truncate(tweet["text"], 120)
                link = f"https://twitter.com/{acct['username']}/status/{tweet['id']}"
                published = tweet.get("created_at", datetime.now(timezone.utc).isoformat())

                all_items.append({
                    "id": _make_id(title, link),
                    "title": title,
                    "link": link,
                    "published": published,
                    "source_name": acct["source_name"],
                    "platform": acct["platform"],
                    "summary": _strip_html(tweet["text"]),
                    "author": f"@{acct['username']}",
                })

        except Exception as e:
            errors.append(f"{acct['username']}: {e}")
            continue

    status["X / Twitter"] = {
        "active": len(all_items) > 0,
        "count": len(all_items),
        "error": "; ".join(errors) if errors else None,
    }
    return all_items


# =============================================================================
# AGGREGATION & CACHING
# =============================================================================

def fetch_all_news() -> tuple[list[dict], dict]:
    """Merge all sources, deduplicate by id, sort newest first.

    Returns (items, source_status) where source_status maps source name
    to {active: bool, count: int, error: str|None}.
    """
    status = {}
    all_items = []
    all_items.extend(fetch_rss_sources(status))
    all_items.extend(fetch_google_news(status))
    all_items.extend(fetch_twitter(status))

    # Deduplicate by id
    seen = set()
    unique = []
    for item in all_items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    # Sort newest first
    unique.sort(key=lambda x: x["published"], reverse=True)
    return unique, status


def get_news(force_refresh: bool = False) -> tuple[list[dict], dict]:
    """Main entry point - returns (items, source_status) with JSON file caching (10-min TTL).

    source_status maps each source name to {active, count, error}.
    """
    if not force_refresh and CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text())
            cached_at = cache.get("cached_at", 0)
            if time.time() - cached_at < CACHE_TTL_SECONDS:
                return cache.get("items", []), cache.get("source_status", {})
        except (json.JSONDecodeError, KeyError):
            pass

    items, source_status = fetch_all_news()

    # Write cache
    try:
        CACHE_FILE.write_text(json.dumps({
            "cached_at": time.time(),
            "items": items,
            "source_status": source_status,
        }, indent=2))
    except Exception as e:
        print(f"[news_fetcher] Cache write error: {e}")

    return items, source_status


# =============================================================================
# NARRATIVE DETECTION
# =============================================================================

def detect_narratives(items: list[dict]) -> pd.DataFrame:
    """Keyword-match articles to narrative topics.

    Returns a DataFrame with columns: Narrative, Polymarket, Kalshi, Total.
    Sorted by Total descending, only rows with >= 1 article.
    """
    counts = {}  # narrative -> {"polymarket": int, "kalshi": int}

    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        platform = item.get("platform", "")

        for narrative, keywords in NARRATIVE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                if narrative not in counts:
                    counts[narrative] = {"polymarket": 0, "kalshi": 0}
                if platform == "polymarket":
                    counts[narrative]["polymarket"] += 1
                elif platform == "kalshi":
                    counts[narrative]["kalshi"] += 1
                elif platform == "both":
                    counts[narrative]["polymarket"] += 1
                    counts[narrative]["kalshi"] += 1

    if not counts:
        return pd.DataFrame(columns=["Narrative", "Polymarket", "Kalshi", "Total"])

    rows = []
    for narrative, c in counts.items():
        total = c["polymarket"] + c["kalshi"]
        if total >= 1:
            rows.append({
                "Narrative": narrative,
                "Polymarket": c["polymarket"],
                "Kalshi": c["kalshi"],
                "Total": total,
            })

    df = pd.DataFrame(rows)
    df = df.sort_values("Total", ascending=False).reset_index(drop=True)
    return df


def detect_narratives_with_articles(items: list[dict]) -> dict[str, list[dict]]:
    """Return a mapping of narrative -> list of matching articles (with link info).

    Each article entry: {title, link, platform, source_name, published}
    """
    result = {}  # narrative -> [articles]

    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()

        for narrative, keywords in NARRATIVE_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                if narrative not in result:
                    result[narrative] = []
                result[narrative].append({
                    "title": item["title"],
                    "link": item["link"],
                    "platform": item.get("platform", ""),
                    "source_name": item.get("source_name", ""),
                    "published": item.get("published", ""),
                })

    return result


def detect_priority_alerts(items: list[dict]) -> list[dict]:
    """Scan articles for platform structural / service / breaking changes.

    Returns a list of dicts sorted by recency:
        {title, link, published, platform, source_name, categories: list[str]}

    Only articles matching at least one PRIORITY_KEYWORDS category are returned.
    """
    alerts = []
    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        matched = [cat for cat, kws in PRIORITY_KEYWORDS.items() if any(kw in text for kw in kws)]
        if matched:
            alerts.append({
                "title": item["title"],
                "link": item["link"],
                "published": item["published"],
                "platform": item.get("platform", ""),
                "source_name": item.get("source_name", ""),
                "categories": matched,
            })

    alerts.sort(key=lambda x: x["published"], reverse=True)
    return alerts
