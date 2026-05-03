"""
Global-Pulse – News RSS Adapter
Parses multiple maritime / trade news RSS feeds and returns
normalised article dicts ready for database insertion.

Environment variables:
    NEWS_RSS_URLS  – comma-separated list of RSS feed URLs
                     (falls back to the built-in defaults below)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
#  Default RSS feeds focused on maritime / trade / logistics
# ──────────────────────────────────────────────────────────────

DEFAULT_RSS_FEEDS: list[str] = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://www.hellenicshippingnews.com/feed/",
    "https://splash247.com/feed/",
    "https://www.tradewindsnews.com/rss",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
]

MARITIME_KEYWORDS = frozenset({
    "ship", "vessel", "port", "freight", "cargo", "maritime",
    "shipping", "container", "logistics", "supply chain", "trade",
    "import", "export", "tariff", "canal", "suez", "panama",
})


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _get_feed_urls() -> list[str]:
    env_val = os.getenv("NEWS_RSS_URLS", "")
    if env_val:
        return [u.strip() for u in env_val.split(",") if u.strip()]
    return DEFAULT_RSS_FEEDS


def _parse_published(entry: Any) -> datetime:
    """Best-effort datetime extraction from a feedparser entry."""
    # feedparser parses to a time.struct_time in 'published_parsed'
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        import time
        return datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
    # Fall back to raw 'published' string
    if hasattr(entry, "published") and entry.published:
        try:
            return parsedate_to_datetime(entry.published).astimezone(timezone.utc)
        except Exception:  # noqa: BLE001
            pass
    return datetime.now(timezone.utc)


def _extract_tags(entry: Any) -> str:
    """Extract tags/categories from a feed entry, joined by comma."""
    tags: list[str] = []
    if hasattr(entry, "tags"):
        tags = [t.get("term", "") for t in entry.tags if t.get("term")]
    elif hasattr(entry, "category"):
        tags = [entry.category]
    return ",".join(tags)[:500]


def _is_relevant(entry: Any) -> bool:
    """Return True if the article appears to be maritime/trade related."""
    text = " ".join([
        getattr(entry, "title", ""),
        getattr(entry, "summary", ""),
    ]).lower()
    return any(kw in text for kw in MARITIME_KEYWORDS)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type(EnvironmentError),
    reraise=True,
)
def _fetch_feed(url: str) -> list[dict[str, Any]]:
    """Parse a single RSS feed URL and return normalised article dicts."""
    logger.info("Parsing RSS feed: %s", url)
    feed = feedparser.parse(url)

    articles: list[dict[str, Any]] = []
    for entry in feed.entries:
        # Skip entries without a URL
        link = getattr(entry, "link", None)
        if not link:
            continue

        articles.append({
            "published_at": _parse_published(entry),
            "title": getattr(entry, "title", "Untitled")[:500],
            "summary": getattr(entry, "summary", None),
            "url": link[:1000],
            "source_feed": url[:255],
            "tags": _extract_tags(entry),
        })

    logger.info("Parsed %d articles from %s", len(articles), url)
    return articles


def fetch_news_articles(
    feed_urls: list[str] | None = None,
    *,
    maritime_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Fetch and parse all configured RSS feeds.

    Args:
        feed_urls:      Override the default feed URL list.
        maritime_only:  When True, filters to maritime/trade relevant articles.

    Returns:
        Deduplicated list of normalised article dicts (keyed by URL).
    """
    urls = feed_urls or _get_feed_urls()
    seen_urls: set[str] = set()
    all_articles: list[dict[str, Any]] = []

    for url in urls:
        try:
            articles = _fetch_feed(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch feed %s: %s", url, exc)
            continue

        for article in articles:
            if article["url"] in seen_urls:
                continue
            seen_urls.add(article["url"])
            all_articles.append(article)

    if maritime_only:
        # Re-create a minimal feedparser-like object to reuse _is_relevant
        class _FakeEntry:
            def __init__(self, a: dict) -> None:
                self.title = a["title"]
                self.summary = a.get("summary", "")

        all_articles = [a for a in all_articles if _is_relevant(_FakeEntry(a))]

    logger.info(
        "Total articles fetched: %d (maritime_only=%s)", len(all_articles), maritime_only
    )
    return all_articles
