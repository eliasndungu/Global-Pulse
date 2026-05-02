"""
Global-Pulse – News RSS Ingestion DAG
======================================
Parses multiple maritime/trade RSS feeds and stores new articles
in the `news_articles` table.  Duplicate URLs are silently ignored
via the UNIQUE constraint on the `url` column.

Schedule: every hour
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

DEFAULT_ARGS = {
    "owner": "global-pulse",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


# ──────────────────────────────────────────────────────────────
#  Task callables
# ──────────────────────────────────────────────────────────────

def fetch_and_store_news(**context) -> int:
    """Fetch all RSS feeds and insert new articles into TimescaleDB."""
    from adapters.news_adapter import fetch_news_articles
    from db.connection import db_session
    from db.models import NewsArticle
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    articles = fetch_news_articles(maritime_only=True)

    if not articles:
        return 0

    inserted = 0
    with db_session() as session:
        for art in articles:
            stmt = (
                pg_insert(NewsArticle.__table__)
                .values(**art)
                .on_conflict_do_nothing(index_elements=["url"])
            )
            result = session.execute(stmt)
            inserted += result.rowcount

    return inserted


def compute_news_sentiment(**context) -> None:
    """
    Placeholder for NLP-based sentiment analysis on recent headlines.
    A future task can extend this with a HuggingFace or TextBlob pipeline.
    """
    from db.connection import db_session
    from sqlalchemy import text

    # Log top 10 latest headlines for observability
    sql = """
        SELECT title, published_at, source_feed
        FROM news_articles
        ORDER BY published_at DESC
        LIMIT 10;
    """

    with db_session() as session:
        rows = session.execute(text(sql)).fetchall()

    for row in rows:
        print(f"[{row[1]}] {row[0]} ({row[2]})")


# ──────────────────────────────────────────────────────────────
#  DAG definition
# ──────────────────────────────────────────────────────────────

with DAG(
    dag_id="news_ingestion",
    description="Parse maritime/trade RSS feeds and store articles",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2024, 1, 1),
    schedule_interval="@hourly",
    catchup=False,
    max_active_runs=1,
    tags=["news", "rss", "ingestion", "global-pulse"],
) as dag:

    fetch_news = PythonOperator(
        task_id="fetch_and_store_news",
        python_callable=fetch_and_store_news,
    )

    sentiment_task = PythonOperator(
        task_id="compute_news_sentiment",
        python_callable=compute_news_sentiment,
    )

    fetch_news >> sentiment_task  # type: ignore[operator]
