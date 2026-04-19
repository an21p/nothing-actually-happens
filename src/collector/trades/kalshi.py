"""Kalshi trade-tape collector scaffold.

Not functional — raises NotImplementedError until credentials are provisioned
and the API client is wired in. Exists so the runner's --venues flag validates
cleanly and the package shape is in place for a later follow-up.
"""
import os
from dataclasses import dataclass
from typing import Iterator


@dataclass
class KalshiConfig:
    api_key_id: str | None = None
    api_key_secret: str | None = None
    api_base: str = "https://api.elections.kalshi.com/trade-api/v2"

    @classmethod
    def from_env(cls) -> "KalshiConfig":
        return cls(
            api_key_id=os.getenv("KALSHI_API_KEY_ID"),
            api_key_secret=os.getenv("KALSHI_API_KEY_SECRET"),
            api_base=os.getenv("KALSHI_API_BASE", cls.api_base),
        )


def fetch_trades(market, config: KalshiConfig) -> Iterator[dict]:
    if not config.api_key_id or not config.api_key_secret:
        raise NotImplementedError(
            "Kalshi collector not configured. Set KALSHI_API_KEY_ID and "
            "KALSHI_API_KEY_SECRET in .env to activate."
        )
    raise NotImplementedError("Kalshi trade fetching not yet implemented.")
