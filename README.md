# Global-Pulse 🌍

> **Data-as-a-Service (DaaS) platform for global maritime shipping intelligence**

Global-Pulse ingests real-time maritime AIS data, weather observations, and
trade news into a [TimescaleDB](https://www.timescale.com/) hypertable, runs
AI-powered delay forecasts, and exposes the results via an API-Key-authenticated
REST API for B2B customers.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Apache Airflow                         │
│  ┌────────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │ maritime_dag   │ │ weather_dag  │ │  news_dag (RSS)  │  │
│  └───────┬────────┘ └──────┬───────┘ └────────┬─────────┘  │
└──────────┼─────────────────┼──────────────────┼────────────┘
           │  Adapters (spiders)                │
           ▼                 ▼                  ▼
  ┌─────────────────────────────────────────────────────────┐
  │            TimescaleDB (PostgreSQL + extension)         │
  │  vessel_positions │ weather_observations │ news_articles │
  │  shipping_routes  │ delay_forecasts      │ api_keys      │
  └──────────────────────────┬──────────────────────────────┘
                             │
                   ┌─────────▼──────────┐
                   │  FastAPI REST API  │
                   │  /v1/maritime      │
                   │  /v1/weather       │
                   │  /v1/news          │
                   │  /v1/forecasting   │
                   │  /v1/api-keys      │
                   └────────────────────┘
```

---

## Folder Structure

```
Global-Pulse/
├── adapters/                   # Data spiders / adapters
│   ├── maritime_adapter.py     #   → MarineTraffic AIS API
│   ├── weather_adapter.py      #   → OpenWeatherMap API
│   └── news_adapter.py         #   → Maritime RSS feeds
├── airflow/
│   └── dags/                   # Airflow ETL DAGs
│       ├── maritime_ingestion_dag.py
│       ├── weather_ingestion_dag.py
│       └── news_ingestion_dag.py
├── api/                        # FastAPI REST API
│   ├── main.py                 #   Application entry-point
│   ├── config.py               #   Settings (pydantic-settings)
│   ├── schemas.py              #   Pydantic request/response models
│   ├── middleware/
│   │   └── auth.py             #   X-API-Key authentication dependency
│   └── routes/
│       ├── api_keys.py         #   Customer & key management
│       ├── maritime.py         #   Vessel positions & routes
│       ├── weather.py          #   Weather observations
│       ├── news.py             #   News articles
│       └── forecasting.py      #   Delay forecast endpoint
├── db/
│   ├── connection.py           # SQLAlchemy engine & session
│   ├── models.py               # ORM models (all tables)
│   ├── settings.py             # DB URL builder
│   └── migrations/
│       └── 001_initial_schema.sql  # TimescaleDB DDL + hypertables
├── forecasting/
│   ├── feature_engineering.py  # Time/weather/congestion features
│   └── delay_predictor.py      # XGBoost + Prophet dual-backend
├── tests/
│   ├── test_adapters.py
│   ├── test_api.py
│   └── test_forecasting.py
├── docker-compose.yml          # Full stack (DB + Airflow + API)
├── Dockerfile                  # API service image
├── requirements.txt
└── .env.example                # Environment variable template
```

---

## Quick Start

### 1. Clone & configure

```bash
git clone https://github.com/eliasndungu/Global-Pulse.git
cd Global-Pulse
cp .env.example .env
# Edit .env with your API keys and secrets
```

### 2. Start the full stack

```bash
docker compose up -d
```

| Service              | URL                        |
|----------------------|----------------------------|
| Airflow Webserver    | http://localhost:8080       |
| Global-Pulse REST API| http://localhost:8000/docs  |
| TimescaleDB          | localhost:5432              |

### 3. Register a B2B customer and get an API key

```bash
# Register customer
curl -s -X POST http://localhost:8000/v1/api-keys/customers \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Shipping", "email": "ops@acme.com"}' | jq .

# Issue API key (replace CUSTOMER_ID)
curl -s -X POST http://localhost:8000/v1/api-keys/customers/CUSTOMER_ID/keys \
  -H "Content-Type: application/json" \
  -d '{"label": "production"}' | jq .
```

### 4. Query the API

```bash
# Get latest vessel positions (use the raw_key from step 3)
curl -H "X-API-Key: YOUR_RAW_KEY" \
  "http://localhost:8000/v1/maritime/vessels?limit=10" | jq .

# Get delay forecast for a route
curl -s -X POST http://localhost:8000/v1/forecasting/predict \
  -H "X-API-Key: YOUR_RAW_KEY" \
  -H "Content-Type: application/json" \
  -d '{"origin_port":"Shanghai","destination_port":"Rotterdam","horizon_days":7}' | jq .
```

---

## ETL Pipeline (Airflow DAGs)

| DAG | Schedule | Description |
|-----|----------|-------------|
| `maritime_ingestion` | Every 10 min | Fetches AIS positions for 4 global regions, aggregates route metrics |
| `weather_ingestion` | Every 30 min | Fetches weather for 10 major world ports, flags severe conditions |
| `news_ingestion` | Hourly | Parses maritime RSS feeds, de-duplicates, stores articles |

---

## Forecasting

The `/v1/forecasting/predict` endpoint uses a **dual-backend ensemble**:

- **XGBoost** – trained on engineered features (cyclic time, weather, congestion score) for point estimates with confidence intervals
- **Prophet** – captures yearly/weekly seasonality in historical transit times

Both models are trained on-demand if no pre-trained file exists, then saved to
`MODEL_STORE_PATH` for fast subsequent inference.

---

## API Authentication

All data endpoints require an `X-API-Key` header.  Keys are:

1. Generated as `secrets.token_urlsafe(32)` (256-bit entropy)
2. Stored as **bcrypt hashes** – the raw key is returned only once at creation
3. Validated via prefix-lookup then bcrypt verify (avoids full-table scans)
4. Auto-expire after `API_KEY_EXPIRE_DAYS` (default 365 days)

---

## Running Tests

```bash
pip install pytest pytest-asyncio httpx feedparser
pytest tests/ -v
```

---

## Environment Variables

See `.env.example` for the full list.  Key variables:

| Variable | Description |
|---|---|
| `MARINETRAFFIC_API_KEY` | MarineTraffic API v2 key |
| `OPENWEATHER_API_KEY` | OpenWeatherMap API key |
| `NEWS_RSS_URLS` | Comma-separated RSS feed URLs |
| `POSTGRES_*` | TimescaleDB connection settings |
| `API_SECRET_KEY` | JWT / HMAC secret (FastAPI) |
| `MODEL_STORE_PATH` | Path to save trained forecast models |
