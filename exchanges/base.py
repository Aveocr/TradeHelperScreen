from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class BaseExchange(ABC):
    """Абстрактный интерфейс для всех бирж."""

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> list[dict]:
        """
        Возвращает список OHLCV-свечей.
        Каждый элемент: {"timestamp": int, "open": float, "high": float,
                          "low": float, "close": float, "volume": float}
        """

    @abstractmethod
    async def get_ticker(self, symbol: str) -> dict:
        """
        Текущий тикер символа.
        {"symbol": str, "last": float, "bid": float, "ask": float,
         "volume_24h": float, "change_24h_pct": float}
        """

    @abstractmethod
    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        """
        Стакан заявок.
        {"bids": [[price, size], ...], "asks": [[price, size], ...]}
        """

    @abstractmethod
    async def get_markets(self, market_type: Optional[str] = None) -> list[dict]:
        """
        Список доступных торговых пар.
        market_type: 'spot' | 'futures' | None (все)
        """
