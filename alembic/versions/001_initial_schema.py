"""Initial schema – all Global-Pulse tables.

This migration creates the same schema as ``db/migrations/001_initial_schema.sql``
but expressed as Alembic Python so it participates in the revision chain.
TimescaleDB-specific DDL (CREATE EXTENSION, create_hypertable, compression
policies) is emitted via ``op.execute()`` because SQLAlchemy has no built-in
support for those statements.

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── TimescaleDB extension ─────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")

    # ── customers ─────────────────────────────────────────────
    op.create_table(
        "customers",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="TRUE"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("NOW()")),
    )

    # ── api_keys ──────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("customer_id", sa.dialects.postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_prefix", sa.String(10), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="TRUE"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── vessel_positions (hypertable) ─────────────────────────
    op.create_table(
        "vessel_positions",
        sa.Column("id", sa.BigInteger, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mmsi", sa.String(20), nullable=False),
        sa.Column("vessel_name", sa.String(255), nullable=True),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("speed_knots", sa.Float, nullable=True),
        sa.Column("heading", sa.Float, nullable=True),
        sa.Column("destination", sa.String(255), nullable=True),
        sa.Column("status", sa.String(50), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="'marinetraffic'"),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )
    op.execute(
        "SELECT create_hypertable('vessel_positions', 'timestamp', "
        "if_not_exists => TRUE, migrate_data => TRUE);"
    )
    op.create_index("idx_vessel_positions_mmsi", "vessel_positions", ["mmsi", "timestamp"])

    # ── shipping_routes (hypertable) ──────────────────────────
    op.create_table(
        "shipping_routes",
        sa.Column("id", sa.BigInteger, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin_port", sa.String(100), nullable=False),
        sa.Column("destination_port", sa.String(100), nullable=False),
        sa.Column("vessel_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("avg_transit_days", sa.Float, nullable=True),
        sa.Column("congestion_score", sa.Float, nullable=True),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )
    op.execute(
        "SELECT create_hypertable('shipping_routes', 'timestamp', "
        "if_not_exists => TRUE, migrate_data => TRUE);"
    )

    # ── weather_observations (hypertable) ─────────────────────
    op.create_table(
        "weather_observations",
        sa.Column("id", sa.BigInteger, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("location_name", sa.String(100), nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("temperature_c", sa.Float, nullable=True),
        sa.Column("wind_speed_ms", sa.Float, nullable=True),
        sa.Column("wind_direction", sa.Float, nullable=True),
        sa.Column("wave_height_m", sa.Float, nullable=True),
        sa.Column("visibility_km", sa.Float, nullable=True),
        sa.Column("condition", sa.String(100), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="'openweathermap'"),
        sa.PrimaryKeyConstraint("id", "timestamp"),
    )
    op.execute(
        "SELECT create_hypertable('weather_observations', 'timestamp', "
        "if_not_exists => TRUE, migrate_data => TRUE);"
    )
    op.create_index(
        "idx_weather_location", "weather_observations", ["location_name", "timestamp"]
    )

    # ── news_articles ─────────────────────────────────────────
    op.create_table(
        "news_articles",
        sa.Column("id", sa.BigInteger, autoincrement=True, primary_key=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("url", sa.String(1000), nullable=False, unique=True),
        sa.Column("source_feed", sa.String(255), nullable=False),
        sa.Column("tags", sa.String(500), nullable=True),
        sa.UniqueConstraint("url", name="uq_news_url"),
    )
    op.create_index("idx_news_published", "news_articles", ["published_at"])

    # ── delay_forecasts ───────────────────────────────────────
    op.create_table(
        "delay_forecasts",
        sa.Column("id", sa.BigInteger, autoincrement=True, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("NOW()")),
        sa.Column("origin_port", sa.String(100), nullable=False),
        sa.Column("destination_port", sa.String(100), nullable=False),
        sa.Column("forecast_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_delay_days", sa.Float, nullable=False),
        sa.Column("confidence_lower", sa.Float, nullable=True),
        sa.Column("confidence_upper", sa.Float, nullable=True),
        sa.Column("model_version", sa.String(50), nullable=False),
    )
    op.create_index(
        "idx_forecasts_route",
        "delay_forecasts",
        ["origin_port", "destination_port", "forecast_date"],
    )

    # ── TimescaleDB compression policies ─────────────────────
    op.execute(
        "ALTER TABLE vessel_positions SET ("
        "  timescaledb.compress,"
        "  timescaledb.compress_orderby = 'timestamp DESC',"
        "  timescaledb.compress_segmentby = 'mmsi'"
        ");"
    )
    op.execute(
        "SELECT add_compression_policy('vessel_positions', INTERVAL '30 days', "
        "if_not_exists => TRUE);"
    )
    op.execute(
        "ALTER TABLE weather_observations SET ("
        "  timescaledb.compress,"
        "  timescaledb.compress_orderby = 'timestamp DESC',"
        "  timescaledb.compress_segmentby = 'location_name'"
        ");"
    )
    op.execute(
        "SELECT add_compression_policy('weather_observations', INTERVAL '30 days', "
        "if_not_exists => TRUE);"
    )


def downgrade() -> None:
    op.execute("SELECT remove_compression_policy('weather_observations', if_not_exists => TRUE);")
    op.execute("SELECT remove_compression_policy('vessel_positions', if_not_exists => TRUE);")
    op.drop_table("delay_forecasts")
    op.drop_table("news_articles")
    op.drop_table("weather_observations")
    op.drop_table("shipping_routes")
    op.drop_table("vessel_positions")
    op.drop_table("api_keys")
    op.drop_table("customers")
