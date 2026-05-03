"""
Tests – Data Adapters
Tests the maritime, weather, and news adapters using mocked HTTP
responses so no live API keys are required.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────
#  Maritime Adapter
# ──────────────────────────────────────────────────────────────

SAMPLE_VESSEL_RESPONSE = {
    "data": [
        {
            "MMSI": "123456789",
            "SHIPNAME": "MV TEST CARGO",
            "LAT": "1.3521",
            "LON": "103.8198",
            "SPEED": "12.5",
            "HEADING": "45",
            "DESTINATION": "ROTTERDAM",
            "STATUS": "underway",
            "TIMESTAMP": "2024-01-15T10:30:00",
        }
    ]
}


def test_maritime_adapter_parses_vessels(monkeypatch):
    """Maritime adapter correctly normalises a MarineTraffic response."""
    monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test_key")

    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_VESSEL_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("adapters.maritime_adapter.requests.get", return_value=mock_response):
        from adapters.maritime_adapter import fetch_vessel_positions

        vessels = fetch_vessel_positions()

    assert len(vessels) == 1
    v = vessels[0]
    assert v["mmsi"] == "123456789"
    assert v["vessel_name"] == "MV TEST CARGO"
    assert v["latitude"] == pytest.approx(1.3521)
    assert v["longitude"] == pytest.approx(103.8198)
    assert v["speed_knots"] == pytest.approx(12.5)
    assert v["destination"] == "ROTTERDAM"
    assert isinstance(v["timestamp"], datetime)
    assert v["source"] == "marinetraffic"


def test_maritime_adapter_requires_api_key(monkeypatch):
    """fetch_vessel_positions raises EnvironmentError when API key is missing."""
    monkeypatch.delenv("MARINETRAFFIC_API_KEY", raising=False)

    with pytest.raises(EnvironmentError, match="MARINETRAFFIC_API_KEY"):
        # Patch os.getenv inside the adapter so the module reload is not needed
        with patch("adapters.maritime_adapter.os.getenv", return_value=""):
            from adapters.maritime_adapter import fetch_vessel_positions
            fetch_vessel_positions()


def test_maritime_adapter_handles_empty_response(monkeypatch):
    """Empty API response returns an empty list."""
    monkeypatch.setenv("MARINETRAFFIC_API_KEY", "test_key")

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": []}
    mock_response.raise_for_status = MagicMock()

    with patch("adapters.maritime_adapter.requests.get", return_value=mock_response):
        from adapters.maritime_adapter import fetch_vessel_positions
        vessels = fetch_vessel_positions()

    assert vessels == []


# ──────────────────────────────────────────────────────────────
#  Weather Adapter
# ──────────────────────────────────────────────────────────────

SAMPLE_WEATHER_RESPONSE = {
    "dt": 1705315800,
    "main": {"temp": 28.5},
    "wind": {"speed": 5.2, "deg": 180},
    "weather": [{"description": "clear sky"}],
    "visibility": 10000,
}


def test_weather_adapter_parses_observation(monkeypatch):
    """Weather adapter correctly normalises an OpenWeatherMap response."""
    monkeypatch.setenv("OPENWEATHER_API_KEY", "test_key")

    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_WEATHER_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("adapters.weather_adapter.requests.get", return_value=mock_response):
        from adapters.weather_adapter import fetch_weather_for_port

        obs = fetch_weather_for_port("Singapore", 1.2897, 103.8501)

    assert obs["location_name"] == "Singapore"
    assert obs["temperature_c"] == pytest.approx(28.5)
    assert obs["wind_speed_ms"] == pytest.approx(5.2)
    assert obs["wind_direction"] == pytest.approx(180)
    assert obs["visibility_km"] == pytest.approx(10.0)
    assert obs["condition"] == "clear sky"
    assert obs["source"] == "openweathermap"
    assert isinstance(obs["timestamp"], datetime)


def test_weather_adapter_requires_api_key(monkeypatch):
    """fetch_weather_for_port raises EnvironmentError when API key is missing."""
    monkeypatch.delenv("OPENWEATHER_API_KEY", raising=False)

    with pytest.raises(EnvironmentError, match="OPENWEATHER_API_KEY"):
        with patch("adapters.weather_adapter.os.getenv", return_value=""):
            from adapters.weather_adapter import fetch_weather_for_port
            fetch_weather_for_port("Singapore", 1.29, 103.85)


# ──────────────────────────────────────────────────────────────
#  News Adapter
# ──────────────────────────────────────────────────────────────

SAMPLE_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Maritime News</title>
    <item>
      <title>Container ship delays hit Suez Canal</title>
      <link>https://example.com/shipping-delays</link>
      <description>Major cargo vessel delays reported at Suez Canal.</description>
      <pubDate>Mon, 15 Jan 2024 10:00:00 +0000</pubDate>
      <category>maritime</category>
    </item>
    <item>
      <title>Local sports event</title>
      <link>https://example.com/sports</link>
      <description>A local football match was played.</description>
      <pubDate>Mon, 15 Jan 2024 11:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


def test_news_adapter_parses_feed():
    """News adapter parses RSS and filters for maritime content."""
    from adapters.news_adapter import _parse_published, _is_relevant, fetch_news_articles
    from datetime import datetime, timezone

    # Create a mock feedparser-like entry class
    class MockEntry:
        title = "Container ship delays hit Suez Canal"
        link = "https://example.com/shipping-delays"
        summary = "Major cargo vessel delays reported at Suez Canal."
        published = "Mon, 15 Jan 2024 10:00:00 +0000"
        published_parsed = None  # will fall back to published string
        tags = []
        category = "maritime"

    class MockFeed:
        entries = [MockEntry()]

    with patch("adapters.news_adapter.feedparser.parse", return_value=MockFeed()):
        articles = fetch_news_articles(
            feed_urls=["https://example.com/rss"],
            maritime_only=True,
        )

    assert len(articles) >= 1
    titles = [a["title"] for a in articles]
    assert any("Suez" in t or "ship" in t.lower() or "cargo" in t.lower() for t in titles)


def test_news_adapter_deduplicates_articles():
    """News adapter removes duplicate URLs across feeds."""
    class MockEntry:
        title = "Freight volumes at record high"
        link = "https://example.com/freight-volumes"
        summary = "Cargo shipping volumes reach a new record."
        published = "Mon, 15 Jan 2024 11:00:00 +0000"
        published_parsed = None
        tags = []

    class MockFeed:
        entries = [MockEntry()]

    with patch("adapters.news_adapter.feedparser.parse", return_value=MockFeed()):
        from adapters.news_adapter import fetch_news_articles

        articles = fetch_news_articles(
            feed_urls=["https://example.com/rss1", "https://example.com/rss2"],
            maritime_only=False,
        )

    urls = [a["url"] for a in articles]
    assert len(urls) == len(set(urls)), "Duplicate URLs found in output"
