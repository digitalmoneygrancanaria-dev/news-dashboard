"""Platform Health Monitoring - API health checks, schema validation, SDK tracking.

Monitors Polymarket (Gamma, CLOB) and Kalshi (Exchange, Markets) APIs for
uptime, latency, schema drift, fee changes, and SDK version updates.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from packaging.version import Version

# =============================================================================
# CONSTANTS
# =============================================================================

HEALTH_CACHE_FILE = Path(__file__).parent / "health_cache.json"
HEALTH_CACHE_TTL = 120          # 2 minutes
LATENCY_SLOW = 2.0             # seconds
LATENCY_DEGRADED = 5.0
REQUEST_TIMEOUT = 8
BOT_PINNED_VERSION = "0.17.0"  # from mat-trade/requirements.txt

# =============================================================================
# ENDPOINT DEFINITIONS
# =============================================================================

ENDPOINTS = [
    {
        "name": "Gamma API",
        "platform": "Polymarket",
        "url": "https://gamma-api.polymarket.com/events?limit=1&active=true&closed=false",
        "expected_keys": ["id", "title", "endDate", "markets"],
        "nested_schema": {
            "path": "markets",
            "expected_keys": [
                "id", "conditionId", "outcomePrices", "clobTokenIds",
                "outcomes", "closed", "volume", "acceptingOrders",
            ],
        },
        "response_type": "list",
    },
    {
        "name": "CLOB API",
        "platform": "Polymarket",
        "url": "https://clob.polymarket.com/markets?limit=1",
        "expected_keys": [
            "condition_id", "tokens", "active", "accepting_orders",
            "maker_base_fee", "taker_base_fee",
        ],
        "nested_schema": None,
        "response_type": "dict_wrapped_list",
        "wrapper_key": "data",
        "fee_fields": ["maker_base_fee", "taker_base_fee"],
    },
    {
        "name": "Exchange Status",
        "platform": "Kalshi",
        "url": "https://api.elections.kalshi.com/trade-api/v2/exchange/status",
        "expected_keys": ["exchange_active", "trading_active"],
        "nested_schema": None,
        "response_type": "dict",
    },
    {
        "name": "Markets API",
        "platform": "Kalshi",
        "url": "https://api.elections.kalshi.com/trade-api/v2/markets?limit=1&status=open",
        "expected_keys": [
            "ticker", "status", "result", "yes_bid", "yes_ask",
            "no_bid", "no_ask", "last_price", "title",
        ],
        "nested_schema": None,
        "response_type": "dict_wrapped_list",
        "wrapper_key": "markets",
    },
]

# =============================================================================
# SCHEMA VALIDATION
# =============================================================================

def _validate_schema(data, endpoint: dict) -> tuple[bool, list[str], dict]:
    """Validate response data against expected schema.

    Returns (schema_ok, missing_keys, extracted_fields).
    """
    missing_keys = []
    extracted_fields = {}

    # Get the record to check
    record = None
    resp_type = endpoint.get("response_type", "dict")

    if resp_type == "list":
        if isinstance(data, list) and len(data) > 0:
            record = data[0]
    elif resp_type == "dict_wrapped_list":
        wrapper_key = endpoint.get("wrapper_key", "")
        if isinstance(data, dict) and wrapper_key in data:
            items = data[wrapper_key]
            if isinstance(items, list) and len(items) > 0:
                record = items[0]
    elif resp_type == "dict":
        record = data if isinstance(data, dict) else None

    if record is None:
        return False, ["(no data to validate)"], {}

    # Check top-level expected keys
    for key in endpoint.get("expected_keys", []):
        if key not in record:
            missing_keys.append(key)

    # Extract fee fields if defined
    for field in endpoint.get("fee_fields", []):
        if field in record:
            extracted_fields[field] = record[field]

    # Check nested schema if defined
    nested = endpoint.get("nested_schema")
    if nested and record:
        nested_path = nested["path"]
        nested_data = record.get(nested_path)
        if isinstance(nested_data, list) and len(nested_data) > 0:
            nested_record = nested_data[0]
            for key in nested.get("expected_keys", []):
                if key not in nested_record:
                    missing_keys.append(f"{nested_path}[].{key}")
        elif nested_data is None:
            missing_keys.append(f"{nested_path} (missing)")

    schema_ok = len(missing_keys) == 0
    return schema_ok, missing_keys, extracted_fields


# =============================================================================
# ENDPOINT HEALTH CHECKS
# =============================================================================

def check_endpoint(endpoint: dict) -> dict:
    """Check a single API endpoint for health, latency, and schema validity."""
    result = {
        "name": endpoint["name"],
        "platform": endpoint["platform"],
        "url": endpoint["url"],
        "status": "DOWN",
        "http_status": None,
        "latency_ms": None,
        "schema_ok": None,
        "missing_keys": [],
        "field_changes": {},
        "extra_info": {},
        "error": None,
    }

    try:
        start = time.monotonic()
        resp = requests.get(endpoint["url"], timeout=REQUEST_TIMEOUT)
        elapsed = time.monotonic() - start
        latency_s = elapsed
        latency_ms = round(elapsed * 1000)

        result["http_status"] = resp.status_code
        result["latency_ms"] = latency_ms

        if resp.status_code != 200:
            result["status"] = "DOWN"
            result["error"] = f"HTTP {resp.status_code}"
            return result

        # Determine status from latency
        if latency_s >= LATENCY_DEGRADED:
            result["status"] = "DEGRADED"
        elif latency_s >= LATENCY_SLOW:
            result["status"] = "SLOW"
        else:
            result["status"] = "UP"

        # Parse and validate schema
        data = resp.json()
        schema_ok, missing_keys, extracted_fields = _validate_schema(data, endpoint)
        result["schema_ok"] = schema_ok
        result["missing_keys"] = missing_keys
        result["field_changes"] = extracted_fields

        # Extract extra info for specific endpoints
        if endpoint["name"] == "Exchange Status" and isinstance(data, dict):
            result["extra_info"] = {
                "exchange_active": data.get("exchange_active"),
                "trading_active": data.get("trading_active"),
            }

    except requests.exceptions.Timeout:
        result["status"] = "DOWN"
        result["error"] = "Request timed out"
    except requests.exceptions.ConnectionError:
        result["status"] = "DOWN"
        result["error"] = "Connection failed"
    except Exception as e:
        result["status"] = "DOWN"
        result["error"] = str(e)

    return result


def check_all_endpoints() -> list[dict]:
    """Check all configured endpoints sequentially."""
    return [check_endpoint(ep) for ep in ENDPOINTS]


# =============================================================================
# SDK VERSION CHECKS
# =============================================================================

def check_pypi_version() -> dict:
    """Check PyPI for latest py-clob-client version vs pinned."""
    result = {
        "latest_version": None,
        "pinned_version": BOT_PINNED_VERSION,
        "update_available": False,
        "is_major_bump": False,
        "is_minor_bump": False,
        "release_date": None,
        "pypi_url": "https://pypi.org/project/py-clob-client/",
        "error": None,
    }

    try:
        resp = requests.get(
            "https://pypi.org/pypi/py-clob-client/json",
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            result["error"] = f"PyPI HTTP {resp.status_code}"
            return result

        data = resp.json()
        latest = data.get("info", {}).get("version", "")
        result["latest_version"] = latest

        if latest:
            try:
                pinned_v = Version(BOT_PINNED_VERSION)
                latest_v = Version(latest)
                result["update_available"] = latest_v > pinned_v
                result["is_major_bump"] = latest_v.major > pinned_v.major
                result["is_minor_bump"] = (
                    latest_v.minor > pinned_v.minor and not result["is_major_bump"]
                )
            except Exception:
                pass

        # Get release date of latest version
        releases = data.get("releases", {})
        if latest in releases and releases[latest]:
            upload_time = releases[latest][0].get("upload_time")
            if upload_time:
                result["release_date"] = upload_time

    except Exception as e:
        result["error"] = str(e)

    return result


def check_github_releases() -> dict:
    """Check GitHub for recent py-clob-client releases."""
    result = {
        "latest_release": None,
        "latest_release_date": None,
        "latest_release_url": None,
        "recent_releases": [],
        "error": None,
    }

    try:
        resp = requests.get(
            "https://api.github.com/repos/Polymarket/py-clob-client/releases?per_page=5",
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        if resp.status_code != 200:
            result["error"] = f"GitHub HTTP {resp.status_code}"
            return result

        releases = resp.json()
        if not releases:
            result["error"] = "No releases found"
            return result

        result["latest_release"] = releases[0].get("tag_name", "")
        result["latest_release_date"] = releases[0].get("published_at", "")
        result["latest_release_url"] = releases[0].get("html_url", "")

        result["recent_releases"] = [
            {
                "tag": r.get("tag_name", ""),
                "date": r.get("published_at", ""),
                "url": r.get("html_url", ""),
            }
            for r in releases[:5]
        ]

    except Exception as e:
        result["error"] = str(e)

    return result


# =============================================================================
# MAIN ENTRY POINT WITH CACHING
# =============================================================================

def get_health_status(force_refresh: bool = False) -> dict:
    """Main entry point - returns full health status with 2-min JSON cache.

    Returns dict with keys:
        endpoints, sdk_version, github_releases, kalshi_exchange,
        fee_status, overall_status, checked_at
    """
    # Check cache
    if not force_refresh and HEALTH_CACHE_FILE.exists():
        try:
            cache = json.loads(HEALTH_CACHE_FILE.read_text())
            cached_at = cache.get("cached_at", 0)
            if time.time() - cached_at < HEALTH_CACHE_TTL:
                return cache
        except (json.JSONDecodeError, KeyError):
            pass

    # Fetch fresh data
    endpoints = check_all_endpoints()
    sdk_version = check_pypi_version()
    github_releases = check_github_releases()

    # Extract Kalshi exchange info
    kalshi_exchange = {}
    for ep in endpoints:
        if ep["name"] == "Exchange Status":
            kalshi_exchange = ep.get("extra_info", {})
            break

    # Extract fee status from CLOB
    fee_status = {}
    for ep in endpoints:
        if ep["name"] == "CLOB API":
            fee_status = ep.get("field_changes", {})
            break

    # Determine overall status
    statuses = [ep["status"] for ep in endpoints]
    schema_issues = any(ep["schema_ok"] is False for ep in endpoints)

    if "DOWN" in statuses:
        overall_status = "CRITICAL"
    elif any(s in ("SLOW", "DEGRADED") for s in statuses) or schema_issues or sdk_version.get("is_major_bump"):
        overall_status = "WARNING"
    else:
        overall_status = "HEALTHY"

    result = {
        "cached_at": time.time(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "endpoints": endpoints,
        "sdk_version": sdk_version,
        "github_releases": github_releases,
        "kalshi_exchange": kalshi_exchange,
        "fee_status": fee_status,
        "overall_status": overall_status,
    }

    # Write cache
    try:
        HEALTH_CACHE_FILE.write_text(json.dumps(result, indent=2))
    except Exception as e:
        print(f"[platform_monitor] Cache write error: {e}")

    return result
