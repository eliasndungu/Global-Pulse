FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2, Prophet, XGBoost
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install only the packages needed for the API (exclude Airflow)
RUN pip install --no-cache-dir \
        fastapi==0.111.0 \
        uvicorn[standard]==0.29.0 \
        python-multipart==0.0.9 \
        psycopg2-binary==2.9.9 \
        SQLAlchemy==2.0.30 \
        alembic==1.13.1 \
        httpx==0.27.0 \
        requests==2.32.3 \
        feedparser==6.0.11 \
        pandas==2.2.2 \
        numpy==1.26.4 \
        scikit-learn==1.5.0 \
        xgboost==2.0.3 \
        prophet==1.1.5 \
        passlib[bcrypt]==1.7.4 \
        python-jose[cryptography]==3.3.0 \
        cryptography==42.0.7 \
        pydantic==2.7.1 \
        pydantic-settings==2.2.1 \
        python-dotenv==1.0.1 \
        tenacity==8.3.0 \
        structlog==24.1.0

COPY api/ ./api/
COPY db/ ./db/
COPY forecasting/ ./forecasting/
COPY adapters/ ./adapters/

ENV PYTHONPATH=/app
ENV MODEL_STORE_PATH=/app/model_store

RUN mkdir -p /app/model_store

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
