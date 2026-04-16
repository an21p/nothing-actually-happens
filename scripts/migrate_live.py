"""Idempotent one-off migration to add live-bot schema to an existing DB.

Safe to run against a fresh DB too (no-ops everything because SQLAlchemy
create_all has already done the work). Usage:

    uv run python scripts/migrate_live.py [--db data/polymarket.db]
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


def _columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _table_exists(cur: sqlite3.Cursor, table: str) -> bool:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def migrate(db_path: str) -> None:
    if not os.path.exists(db_path):
        print(f"No DB at {db_path} — nothing to migrate. Run the collector to create it.")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    if _table_exists(cur, "markets"):
        cols = _columns(cur, "markets")
        if "end_date" not in cols:
            cur.execute("ALTER TABLE markets ADD COLUMN end_date TIMESTAMP")
            print("+ markets.end_date")

    if _table_exists(cur, "backtest_results"):
        cols = _columns(cur, "backtest_results")
        for name, ddl in [
            ("size_shares", "ALTER TABLE backtest_results ADD COLUMN size_shares REAL"),
            ("size_notional", "ALTER TABLE backtest_results ADD COLUMN size_notional REAL"),
            ("sizing_rule", "ALTER TABLE backtest_results ADD COLUMN sizing_rule TEXT"),
            ("pnl_notional", "ALTER TABLE backtest_results ADD COLUMN pnl_notional REAL"),
        ]:
            if name not in cols:
                cur.execute(ddl)
                print(f"+ backtest_results.{name}")

    if not _table_exists(cur, "positions"):
        cur.execute(
            """
            CREATE TABLE positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id TEXT NOT NULL REFERENCES markets(id),
                strategy TEXT NOT NULL,
                executor TEXT NOT NULL,
                status TEXT NOT NULL,
                entry_price REAL NOT NULL,
                entry_timestamp TIMESTAMP NOT NULL,
                size_shares REAL NOT NULL,
                size_notional REAL NOT NULL,
                sizing_rule TEXT NOT NULL,
                sizing_params_json TEXT NOT NULL,
                last_mark_price REAL,
                last_mark_timestamp TIMESTAMP,
                unrealized_pnl REAL,
                exit_price REAL,
                exit_timestamp TIMESTAMP,
                realized_pnl REAL,
                created_at TIMESTAMP NOT NULL,
                notes TEXT
            )
            """
        )
        cur.execute("CREATE INDEX idx_positions_market ON positions(market_id)")
        cur.execute("CREATE INDEX idx_positions_status ON positions(status)")
        print("+ positions table")

    conn.commit()
    conn.close()
    print(f"Migration complete: {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    default_db = str(Path("data") / "polymarket.db")
    parser.add_argument("--db", default=default_db)
    args = parser.parse_args()
    migrate(args.db)


if __name__ == "__main__":
    main()
