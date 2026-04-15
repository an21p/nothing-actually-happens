from datetime import datetime

from sqlalchemy import String, Float, DateTime, Text, ForeignKey, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String)
    no_token_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    price_snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="market", order_by="PriceSnapshot.timestamp"
    )
    backtest_results: Mapped[list["BacktestResult"]] = relationship(
        back_populates="market"
    )


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

    market: Mapped["Market"] = relationship(back_populates="backtest_results")
