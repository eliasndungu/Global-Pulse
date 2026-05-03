#!/usr/bin/env python
"""
Global-Pulse – Local Development DB Initialiser
================================================
Creates all tables defined in the ORM models and optionally seeds the
database with sample data so you can explore the API immediately without
running the full Airflow ingestion pipeline.

Usage:
    python scripts/init_db.py            # create tables only
    python scripts/init_db.py --seed     # create tables + insert sample data
    python scripts/init_db.py --seed --drop   # drop-and-recreate + seed

Environment variables are read from `.env` if present.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Make project root importable ─────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import secrets
import uuid

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from db.connection import Base, SessionLocal, engine  # noqa: E402
from db.models import (  # noqa: E402
    APIKey,
    Customer,
    NewsArticle,
    ShippingRoute,
    VesselPosition,
    WeatherObservation,
)
from passlib.context import CryptContext  # noqa: E402

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ──────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_tables(drop_first: bool = False) -> None:
    """Create all ORM-managed tables."""
    if drop_first:
        print("⚠️  Dropping all tables …")
        Base.metadata.drop_all(bind=engine)
    print("✅ Creating tables …")
    Base.metadata.create_all(bind=engine)
    print("   Tables created.")


def seed_sample_data() -> None:
    """Insert a minimal set of sample rows for local exploration."""
    db = SessionLocal()
    try:
        # ── Customer + API Key ────────────────────────────────
        existing = db.query(Customer).filter_by(email="demo@globalpulse.io").first()
        if not existing:
            customer = Customer(
                id=uuid.uuid4(),
                name="Demo Customer",
                email="demo@globalpulse.io",
                is_active=True,
                created_at=_now(),
            )
            db.add(customer)
            db.flush()

            raw_key = secrets.token_urlsafe(32)
            api_key = APIKey(
                id=uuid.uuid4(),
                customer_id=customer.id,
                key_prefix=raw_key[:8],
                key_hash=pwd_ctx.hash(raw_key),
                label="dev-key",
                is_active=True,
                expires_at=_now() + timedelta(days=365),
                created_at=_now(),
            )
            db.add(api_key)
            print(f"\n🔑 Demo API key: {raw_key}")
            print("   Store this key – it won't be shown again.\n")
        else:
            print("   Demo customer already exists; skipping customer/key seed.")

        # ── Vessel Positions ──────────────────────────────────
        if db.query(VesselPosition).count() == 0:
            now = _now()
            positions = [
                VesselPosition(
                    timestamp=now - timedelta(minutes=i * 10),
                    mmsi=f"36600{i:04d}",
                    vessel_name=f"MV GLOBAL PULSE {i}",
                    latitude=1.29 + i * 0.01,
                    longitude=103.85 + i * 0.01,
                    speed_knots=12.5,
                    heading=float(90 + i * 5),
                    destination="Rotterdam",
                    status="Under way using engine",
                    source="marinetraffic",
                )
                for i in range(20)
            ]
            db.add_all(positions)
            print(f"   Inserted {len(positions)} sample vessel positions.")

        # ── Shipping Routes ───────────────────────────────────
        if db.query(ShippingRoute).count() == 0:
            now = _now()
            routes = [
                ShippingRoute(
                    timestamp=now - timedelta(days=d),
                    origin_port="Shanghai",
                    destination_port="Rotterdam",
                    vessel_count=120 + d % 30,
                    avg_transit_days=28.5 + (d % 5) * 0.3,
                    congestion_score=0.4 + (d % 3) * 0.1,
                )
                for d in range(60)
            ]
            db.add_all(routes)
            print(f"   Inserted {len(routes)} sample shipping route metrics.")

        # ── Weather Observations ──────────────────────────────
        if db.query(WeatherObservation).count() == 0:
            now = _now()
            obs = [
                WeatherObservation(
                    timestamp=now - timedelta(hours=h),
                    location_name="Singapore",
                    latitude=1.29,
                    longitude=103.85,
                    temperature_c=29.0 + h % 5,
                    wind_speed_ms=5.0 + h % 3,
                    wind_direction=180.0,
                    wave_height_m=0.5,
                    visibility_km=15.0,
                    condition="Clear",
                    source="openweathermap",
                )
                for h in range(48)
            ]
            db.add_all(obs)
            print(f"   Inserted {len(obs)} sample weather observations.")

        # ── News Articles ─────────────────────────────────────
        if db.query(NewsArticle).count() == 0:
            now = _now()
            articles = [
                NewsArticle(
                    published_at=now - timedelta(hours=i * 6),
                    title=f"Shipping Update #{i}: Container volumes rise at major ports",
                    summary=(
                        "Global container throughput increased this week, "
                        "driven by stronger demand across Asia-Pacific routes."
                    ),
                    url=f"https://example.com/shipping-news/{i}",
                    source_feed="https://example.com/rss",
                    tags="shipping,containers,asia-pacific",
                )
                for i in range(10)
            ]
            db.add_all(articles)
            print(f"   Inserted {len(articles)} sample news articles.")

        db.commit()
        print("\n✅ Sample data inserted successfully.")

    except Exception as exc:
        db.rollback()
        print(f"\n❌ Error seeding data: {exc}", file=sys.stderr)
        raise
    finally:
        db.close()


# ──────────────────────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Initialise the Global-Pulse database.")
    parser.add_argument(
        "--seed", action="store_true", help="Insert sample data after creating tables."
    )
    parser.add_argument(
        "--drop", action="store_true", help="Drop all tables before re-creating them."
    )
    args = parser.parse_args()

    create_tables(drop_first=args.drop)

    if args.seed:
        seed_sample_data()

    print("\n🚀 Database ready.  Start the API with:")
    print("   uvicorn api.main:app --reload --host 0.0.0.0 --port 8000")


if __name__ == "__main__":
    main()
