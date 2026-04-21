from datetime import datetime, timezone

from sqlalchemy import String, Float, DateTime, Text, ForeignKey, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String)
    no_token_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="market", order_by="PriceSnapshot.timestamp"
    )
    backtest_results: Mapped[list["BacktestResult"]] = relationship(
        back_populates="market"
    )
    positions: Mapped[list["Position"]] = relationship(back_populates="market")


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    no_price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String)

    market: Mapped["Market"] = relationship(back_populates="price_snapshots")


class BacktestResult(Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    strategy: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float] = mapped_column(Float)
    profit: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String)
    size_shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    sizing_rule: Mapped[str | None] = mapped_column(String, nullable=True)
    pnl_notional: Mapped[float | None] = mapped_column(Float, nullable=True)

    market: Mapped["Market"] = relationship(back_populates="backtest_results")


class FavoriteStrategy(Base):
    __tablename__ = "favorite_strategies"

    strategy: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    strategy: Mapped[str] = mapped_column(String)
    executor: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    entry_price: Mapped[float] = mapped_column(Float)
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    size_shares: Mapped[float] = mapped_column(Float)
    size_notional: Mapped[float] = mapped_column(Float)
    sizing_rule: Mapped[str] = mapped_column(String)
    sizing_params_json: Mapped[str] = mapped_column(Text)
    last_mark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_mark_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    market: Mapped["Market"] = relationship(back_populates="positions")
