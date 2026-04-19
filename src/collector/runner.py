import argparse
import sys
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot
from src.collector.polymarket_api import fetch_resolved_markets
from src.collector.price_history import fetch_price_history
from src.collector.polygon_chain import fetch_onchain_prices

MIN_CREATED_AT = datetime(2024, 1, 1, tzinfo=timezone.utc)


def upsert_market(session: Session, market_data: dict) -> bool:
    existing = session.get(Market, market_data["id"])
    if existing:
        existing.resolution = market_data["resolution"]
        existing.resolved_at = market_data["resolved_at"]
        existing.source_url = market_data["source_url"]
        return False
    market = Market(**market_data)
    session.add(market)
    return True


def store_price_snapshots(session: Session, snapshots: list[dict], market_id: str):
    existing_timestamps = set(
        row[0]
        for row in session.query(PriceSnapshot.timestamp)
        .filter_by(market_id=market_id)
        .all()
    )
    new_snapshots = [
        PriceSnapshot(**s)
        for s in snapshots
        if s["timestamp"] not in existing_timestamps
    ]
    session.add_all(new_snapshots)


def collect(
    categories: list[str] | None = None,
    limit: int | None = None,
    enrich_onchain: bool = False,
    db_path: str | None = None,
):
    engine = get_engine(db_path)
    session = get_session(engine)

    existing_ids = set(row[0] for row in session.query(Market.id).all())
    earliest = session.query(func.min(Market.created_at)).scalar()

    end_date_max = None
    if earliest:
        end_date_max = earliest.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"Found {len(existing_ids)} existing markets in DB (earliest: {earliest.date()})")
        print(f"Fetching markets created on or before {earliest.date()}...")
    else:
        print("Empty DB, fetching newest markets...")

    markets = fetch_resolved_markets(
        categories=categories, limit=limit, end_date_max=end_date_max
    )
    pre_filter = len(markets)
    markets = [m for m in markets if m["created_at"] >= MIN_CREATED_AT]
    if pre_filter != len(markets):
        print(f"Dropped {pre_filter - len(markets)} markets with created_at < {MIN_CREATED_AT.date()}")
    print(f"Found {len(markets)} markets from API")

    new_count = 0
    skipped_count = 0
    for i, market_data in enumerate(markets):
        is_new = upsert_market(session, market_data)
        if is_new:
            new_count += 1
            session.flush()

            print(f"  [{i+1}/{len(markets)}] NEW {market_data['question'][:60]}...")
            snapshots = []
            for attempt in range(3):
                try:
                    snapshots = fetch_price_history(
                        token_id=market_data["no_token_id"],
                        market_id=market_data["id"],
                    )
                    break
                except (httpx.ReadTimeout, httpx.ConnectTimeout):
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                    else:
                        print(f"    Skipping price history (timeout after 3 attempts)")

            if enrich_onchain:
                onchain = fetch_onchain_prices(
                    no_token_id=market_data["no_token_id"],
                    market_id=market_data["id"],
                    created_at=market_data["created_at"],
                    resolved_at=market_data["resolved_at"],
                )
                snapshots.extend(onchain)

            store_price_snapshots(session, snapshots, market_data["id"])
        else:
            skipped_count += 1

        if (i + 1) % 10 == 0:
            session.commit()

    session.commit()
    session.close()
    engine.dispose()

    print(f"Done. {new_count} new, {skipped_count} skipped (already collected).")


def collect_new(
    session: Session,
    categories: list[str] | None = None,
    enrich_onchain: bool = False,
) -> int:
    """Forward-pass: fetch newest resolved markets, add any missing from the DB.

    Unlike `collect()` (which walks backwards into history), this targets recently
    resolved markets for incremental catch-up. Pagination walks newest-first and
    stops as soon as a full page yields no unknown markets — so every market
    resolved since the last fetch is picked up, however many pages that takes.
    Caller owns the session lifecycle. Returns the number of newly inserted
    markets.
    """
    existing_ids = set(row[0] for row in session.query(Market.id).all())

    markets = fetch_resolved_markets(
        categories=categories, stop_if_all_known=existing_ids
    )
    markets = [m for m in markets if m["created_at"] >= MIN_CREATED_AT]

    new_count = 0
    for market_data in markets:
        is_new = upsert_market(session, market_data)
        if not is_new:
            continue
        session.flush()
        new_count += 1

        snapshots: list[dict] = []
        for attempt in range(3):
            try:
                snapshots = fetch_price_history(
                    token_id=market_data["no_token_id"],
                    market_id=market_data["id"],
                )
                break
            except (httpx.ReadTimeout, httpx.ConnectTimeout):
                if attempt < 2:
                    time.sleep(2 ** attempt)

        if enrich_onchain:
            snapshots.extend(fetch_onchain_prices(
                no_token_id=market_data["no_token_id"],
                market_id=market_data["id"],
                created_at=market_data["created_at"],
                resolved_at=market_data["resolved_at"],
            ))

        store_price_snapshots(session, snapshots, market_data["id"])

    session.commit()
    return new_count


def main():
    parser = argparse.ArgumentParser(description="Collect Polymarket data")
    parser.add_argument("--categories", type=str, default="political,geopolitical", help="Comma-separated categories (default: political,geopolitical)")
    parser.add_argument("--limit", type=int, default=None, help="Max number of markets to fetch")
    parser.add_argument("--enrich-onchain", action="store_true", help="Also fetch on-chain price data from Polygon (slow)")
    args = parser.parse_args()

    categories = args.categories.split(",") if args.categories else None
    collect(categories=categories, limit=args.limit, enrich_onchain=args.enrich_onchain)


if __name__ == "__main__":
    main()
