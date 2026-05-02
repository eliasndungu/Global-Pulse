-- ─────────────────────────────────────────────────────────────
--  Global-Pulse – Initial Database Schema
--  Runs automatically when TimescaleDB container first starts.
--  Requires TimescaleDB extension (pre-installed on the image).
-- ─────────────────────────────────────────────────────────────

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ── Customers ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL,
    email       VARCHAR(255) NOT NULL UNIQUE,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── API Keys ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    key_prefix   VARCHAR(10) NOT NULL,
    key_hash     VARCHAR(255) NOT NULL UNIQUE,
    label        VARCHAR(100),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

-- ── Vessel Positions (TimescaleDB hypertable) ────────────────
CREATE TABLE IF NOT EXISTS vessel_positions (
    id           BIGSERIAL,
    timestamp    TIMESTAMPTZ NOT NULL,
    mmsi         VARCHAR(20)  NOT NULL,
    vessel_name  VARCHAR(255),
    latitude     DOUBLE PRECISION NOT NULL,
    longitude    DOUBLE PRECISION NOT NULL,
    speed_knots  DOUBLE PRECISION,
    heading      DOUBLE PRECISION,
    destination  VARCHAR(255),
    status       VARCHAR(50),
    source       VARCHAR(50)  NOT NULL DEFAULT 'marinetraffic',
    PRIMARY KEY (id, timestamp)
);

SELECT create_hypertable(
    'vessel_positions', 'timestamp',
    if_not_exists => TRUE,
    migrate_data  => TRUE
);

CREATE INDEX IF NOT EXISTS idx_vessel_positions_mmsi
    ON vessel_positions (mmsi, timestamp DESC);

-- ── Shipping Routes (TimescaleDB hypertable) ─────────────────
CREATE TABLE IF NOT EXISTS shipping_routes (
    id                BIGSERIAL,
    timestamp         TIMESTAMPTZ NOT NULL,
    origin_port       VARCHAR(100) NOT NULL,
    destination_port  VARCHAR(100) NOT NULL,
    vessel_count      INTEGER NOT NULL DEFAULT 0,
    avg_transit_days  DOUBLE PRECISION,
    congestion_score  DOUBLE PRECISION,
    PRIMARY KEY (id, timestamp)
);

SELECT create_hypertable(
    'shipping_routes', 'timestamp',
    if_not_exists => TRUE,
    migrate_data  => TRUE
);

-- ── Weather Observations (TimescaleDB hypertable) ────────────
CREATE TABLE IF NOT EXISTS weather_observations (
    id              BIGSERIAL,
    timestamp       TIMESTAMPTZ NOT NULL,
    location_name   VARCHAR(100) NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    temperature_c   DOUBLE PRECISION,
    wind_speed_ms   DOUBLE PRECISION,
    wind_direction  DOUBLE PRECISION,
    wave_height_m   DOUBLE PRECISION,
    visibility_km   DOUBLE PRECISION,
    condition       VARCHAR(100),
    source          VARCHAR(50) NOT NULL DEFAULT 'openweathermap',
    PRIMARY KEY (id, timestamp)
);

SELECT create_hypertable(
    'weather_observations', 'timestamp',
    if_not_exists => TRUE,
    migrate_data  => TRUE
);

CREATE INDEX IF NOT EXISTS idx_weather_location
    ON weather_observations (location_name, timestamp DESC);

-- ── News Articles ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_articles (
    id           BIGSERIAL PRIMARY KEY,
    published_at TIMESTAMPTZ NOT NULL,
    title        VARCHAR(500) NOT NULL,
    summary      TEXT,
    url          VARCHAR(1000) NOT NULL,
    source_feed  VARCHAR(255) NOT NULL,
    tags         VARCHAR(500),
    CONSTRAINT uq_news_url UNIQUE (url)
);

CREATE INDEX IF NOT EXISTS idx_news_published
    ON news_articles (published_at DESC);

-- ── Delay Forecasts ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS delay_forecasts (
    id                    BIGSERIAL PRIMARY KEY,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    origin_port           VARCHAR(100) NOT NULL,
    destination_port      VARCHAR(100) NOT NULL,
    forecast_date         TIMESTAMPTZ NOT NULL,
    predicted_delay_days  DOUBLE PRECISION NOT NULL,
    confidence_lower      DOUBLE PRECISION,
    confidence_upper      DOUBLE PRECISION,
    model_version         VARCHAR(50) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_forecasts_route
    ON delay_forecasts (origin_port, destination_port, forecast_date DESC);

-- ── Compression policies (TimescaleDB) ───────────────────────
-- Compress chunks older than 30 days to save storage
ALTER TABLE vessel_positions SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'timestamp DESC',
    timescaledb.compress_segmentby = 'mmsi'
);
SELECT add_compression_policy('vessel_positions', INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE weather_observations SET (
    timescaledb.compress,
    timescaledb.compress_orderby = 'timestamp DESC',
    timescaledb.compress_segmentby = 'location_name'
);
SELECT add_compression_policy('weather_observations', INTERVAL '30 days', if_not_exists => TRUE);
