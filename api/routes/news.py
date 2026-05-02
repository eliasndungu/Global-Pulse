"""
Global-Pulse – News Routes
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.middleware.auth import require_api_key
from api.schemas import NewsArticleResponse
from db.connection import get_db
from db.models import Customer, NewsArticle

router = APIRouter()


@router.get(
    "/articles",
    response_model=list[NewsArticleResponse],
    summary="Latest maritime/trade news articles",
)
def get_news_articles(
    customer: Annotated[Customer, Depends(require_api_key)],
    db: Annotated[Session, Depends(get_db)],
    keyword: str | None = Query(default=None, description="Filter title/tags by keyword"),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[NewsArticle]:
    q = db.query(NewsArticle).order_by(NewsArticle.published_at.desc())
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(
            NewsArticle.title.ilike(kw) | NewsArticle.tags.ilike(kw)
        )
    return q.limit(limit).all()
