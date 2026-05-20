"""
Slack Search Connector for TraceSage MCP.

Searches messages in Slack channels the bot is a member of.
Uses conversations.history + local TF-IDF ranking — no user token needed.

Setup:
  1. Invite @tracesage to the channels you want indexed
  2. Set SLACK_BOT_TOKEN in .env
  3. Optionally set SLACK_SEARCH_CHANNELS=C02DGH3503A,C02DGH6RMC0 to limit scope

How it works:
  - Fetches recent messages from allowed channels (cached for 10 minutes)
  - Scores each message against the query using TF-IDF + keyword overlap
  - Returns top matches as ConnectorDocument objects
  - Thread replies are fetched and included for full context
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from .config import CACHE_DIR
from .models import ConnectorDocument

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_SLACK_TOKEN       = os.environ.get("SLACK_BOT_TOKEN", "")
_ALLOWED_CHANNELS  = [
    c.strip()
    for c in os.environ.get("SLACK_SEARCH_CHANNELS", "").split(",")
    if c.strip()
]
_CACHE_TTL_SECONDS = 600          # 10-minute message cache
_MAX_MESSAGES      = 200          # messages per channel to index
_MAX_THREAD_DEPTH  = 5            # replies to include per thread
_SLACK_API        = "https://slack.com/api"

SLACK_AVAILABLE = bool(_SLACK_TOKEN)

# ---------------------------------------------------------------------------
# Local cache
# ---------------------------------------------------------------------------
_MSG_CACHE_PATH = CACHE_DIR / "slack_messages.json"


def _load_cache() -> dict[str, Any]:
    if _MSG_CACHE_PATH.exists():
        try:
            data = json.loads(_MSG_CACHE_PATH.read_text(encoding="utf-8"))
            if time.time() - data.get("fetched_at", 0) < _CACHE_TTL_SECONDS:
                return data
        except Exception:
            pass
    return {"fetched_at": 0, "channels": {}}


def _save_cache(data: dict[str, Any]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _MSG_CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Slack API helpers
# ---------------------------------------------------------------------------
def _slack_get(endpoint: str, params: dict[str, str]) -> dict[str, Any]:
    """Make a GET request to the Slack API."""
    if not _SLACK_TOKEN:
        return {"ok": False, "error": "no_token"}
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{_SLACK_API}/{endpoint}?{qs}"
    req = Request(url, headers={"Authorization": f"Bearer {_SLACK_TOKEN}"})
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, Exception):
        return {"ok": False, "error": "request_failed"}


def _get_joined_channels() -> list[dict[str, str]]:
    """Return channels the bot is a member of."""
    result = _slack_get("conversations.list", {
        "types": "public_channel,private_channel",
        "exclude_archived": "true",
        "limit": "200",
    })
    if not result.get("ok"):
        return []
    channels = result.get("channels", [])
    joined = [c for c in channels if c.get("is_member")]

    # Filter to allowed channels if configured
    if _ALLOWED_CHANNELS:
        joined = [c for c in joined if c["id"] in _ALLOWED_CHANNELS]

    return [{"id": c["id"], "name": c.get("name", c["id"])} for c in joined]


def _get_channel_messages(channel_id: str) -> list[dict[str, Any]]:
    """Fetch recent messages from a channel."""
    result = _slack_get("conversations.history", {
        "channel": channel_id,
        "limit": str(_MAX_MESSAGES),
    })
    if not result.get("ok"):
        return []
    return result.get("messages", [])


def _get_thread_replies(channel_id: str, thread_ts: str) -> list[dict[str, Any]]:
    """Fetch replies in a thread."""
    result = _slack_get("conversations.replies", {
        "channel": channel_id,
        "ts": thread_ts,
        "limit": str(_MAX_THREAD_DEPTH),
    })
    if not result.get("ok"):
        return []
    return result.get("messages", [])[1:]  # skip parent message


def _get_user_name(user_id: str, name_cache: dict[str, str]) -> str:
    """Resolve a Slack user ID to display name (cached)."""
    if user_id in name_cache:
        return name_cache[user_id]
    result = _slack_get("users.info", {"user": user_id})
    name = result.get("user", {}).get("real_name", user_id) if result.get("ok") else user_id
    name_cache[user_id] = name
    return name


# ---------------------------------------------------------------------------
# Message indexing
# ---------------------------------------------------------------------------
def _build_index() -> list[dict[str, Any]]:
    """
    Fetch messages from all joined channels and build a flat index.
    Returns a list of dicts: {channel, channel_name, ts, text, thread_ts, url}
    """
    cache = _load_cache()
    channels = _get_joined_channels()

    if not channels:
        return []

    name_cache: dict[str, str] = {}
    index: list[dict[str, Any]] = []

    for ch in channels:
        channel_id   = ch["id"]
        channel_name = ch["name"]
        messages     = _get_channel_messages(channel_id)

        for msg in messages:
            text = msg.get("text", "").strip()
            if not text or msg.get("subtype"):  # skip join/leave messages
                continue

            ts        = msg.get("ts", "")
            thread_ts = msg.get("thread_ts", ts)
            reply_count = msg.get("reply_count", 0)

            # Collect thread replies if any
            thread_text = ""
            if reply_count > 0:
                replies = _get_thread_replies(channel_id, thread_ts)
                thread_text = " | ".join(r.get("text", "") for r in replies if r.get("text"))

            full_text = f"{text} {thread_text}".strip()
            slack_url = f"https://dynatrace-sandbox.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"

            index.append({
                "channel":      channel_id,
                "channel_name": channel_name,
                "ts":           ts,
                "text":         full_text[:1000],
                "url":          slack_url,
                "reply_count":  reply_count,
            })

    cache["fetched_at"] = time.time()
    cache["index"]      = index
    _save_cache(cache)
    return index


def _get_index() -> list[dict[str, Any]]:
    """Return cached index or rebuild."""
    cache = _load_cache()
    if time.time() - cache.get("fetched_at", 0) < _CACHE_TTL_SECONDS:
        return cache.get("index", [])
    return _build_index()


# ---------------------------------------------------------------------------
# Search scoring
# ---------------------------------------------------------------------------
def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1]


def _score(query: str, doc_text: str) -> float:
    query_terms  = set(_tokenize(query))
    doc_terms    = _tokenize(doc_text)
    doc_counter  = Counter(doc_terms)
    doc_term_set = set(doc_terms)

    if not query_terms or not doc_terms:
        return 0.0

    overlap = query_terms & doc_term_set
    if not overlap:
        return 0.0

    # TF-style score weighted by term frequency
    score = sum(math.log(1 + doc_counter[t]) for t in overlap)
    # Boost for high reply count (community-validated answers)
    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def search_slack(query: str, max_results: int = 5) -> list[ConnectorDocument]:
    """
    Search Slack channel history for messages relevant to the query.

    Returns a list of ConnectorDocument objects ranked by relevance.
    Returns empty list if SLACK_BOT_TOKEN is not set or bot has no channels.
    """
    if not SLACK_AVAILABLE:
        return []

    index = _get_index()
    if not index:
        return []

    scored = []
    for msg in index:
        s = _score(query, msg["text"])
        if s > 0:
            scored.append((s, msg))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max_results]

    results = []
    for score, msg in top:
        # Truncate text for display
        preview = msg["text"][:300] + ("..." if len(msg["text"]) > 300 else "")
        results.append(ConnectorDocument(
            source="slack",
            source_type="slack_message",
            title=f"#{msg['channel_name']} — Slack thread",
            url=msg["url"],
            text=preview,
            tags=["slack", msg["channel_name"]],
            trust_level="internal",
            updated_at=msg["ts"],
        ))

    return results


def slack_connector_status() -> dict[str, Any]:
    """Return current status of the Slack connector."""
    if not SLACK_AVAILABLE:
        return {"live": False, "reason": "SLACK_BOT_TOKEN not set"}

    channels = _get_joined_channels()
    return {
        "live": True,
        "channels_indexed": len(channels),
        "channel_names": [c["name"] for c in channels],
        "cache_ttl_seconds": _CACHE_TTL_SECONDS,
        "max_messages_per_channel": _MAX_MESSAGES,
    }
