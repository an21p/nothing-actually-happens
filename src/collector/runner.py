import argparse
import sys

from sqlalchemy.orm import Session

from src.storage.db import get_engine, get_session
from src.storage.models import Market, PriceSnapshot
from src.collector.polymarket_api import fetch_resolved_markets
from src.collector.price_history import fetch_price_history
from src.collector.polygon_chain import fetch_onchain_prices


def upsert_market(session: Session, market_data: dict) -> bool:
    existing = session.get(Market, market_data["id"])
    if existing:
        existing.resolution = market_data["resolution"]
        existing.resolved_at = market_data["resolved_at"]
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

    print(f"Fetching resolved markets from Polymarket API...")
    markets = fetch_resolved_markets(categories=categories, limit=limit)
    print(f"Found {len(markets)} markets")

    new_count = 0
    for i, market_data in enumerate(markets):
        is_new = upsert_market(session, market_data)
        if is_new:
            new_count += 1
        session.flush()

        print(f"  [{i+1}/{len(markets)}] {market_data['question'][:60]}...")
        snapshots = fetch_price_history(
            token_id=market_data["no_token_id"],
            market_id=market_data["id"],
        )

        if enrich_onchain:
            onchain = fetch_onchain_prices(
                no_token_id=market_data["no_token_id"],
                market_id=market_data["id"],
                created_at=market_data["created_at"],
                resolved_at=market_data["resolved_at"],
            )
            snapshots.extend(onchain)

        store_price_snapshots(session, snapshots, market_data["id"])

        if (i + 1) % 10 == 0:
            session.commit()

    session.commit()
    session.close()
    engine.dispose()

    print(f"Done. {new_count} new markets added, {len(markets) - new_count} updated.")


def main():
    parser = argparse.ArgumentParser(description="Collect Polymarket data")
    parser.add_argument("--categories", type=str, default=None, help="Comma-separated categories: geopolitical,political,culture")
    parser.add_argument("--limit", type=int, default=None, help="Max number of markets to fetch")
    parser.add_argument("--enrich-onchain", action="store_true", help="Also fetch on-chain price data from Polygon (slow)")
    args = parser.parse_args()

    categories = args.categories.split(",") if args.categories else None
    collect(categories=categories, limit=args.limit, enrich_onchain=args.enrich_onchain)


if __name__ == "__main__":
    main()
