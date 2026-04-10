from __future__ import annotations

import pandas as pd

from core.logger import get_logger
from exchanges.gate import GateExchange

logger = get_logger(__name__)


class MarketDataService:
    """
    Сервис для получения и первичной обработки рыночных данных с Gate.io.
    Возвращает pandas DataFrame для дальнейшего технического анализа.
    """

    def __init__(self, exchange: GateExchange) -> None:
        self._exchange = exchange

    async def get_ohlcv_df(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 200,
        market_type: str = "spot",
    ) -> pd.DataFrame:
        """
        Получает OHLCV и возвращает DataFrame с типизированными колонками.

        Колонки: timestamp (datetime, UTC), open, high, low, close, volume
        """
        raw = await self._exchange.get_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            market_type=market_type,
        )

        df = pd.DataFrame(raw)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp").sort_index()
        df = df.astype({
            "open":   float,
            "high":   float,
            "low":    float,
            "close":  float,
            "volume": float,
        })

        logger.debug(
            f"OHLCV загружен | {symbol} | {timeframe} | "
            f"{market_type} | свечей: {len(df)}"
        )
        return df

    async def get_ticker(
        self,
        symbol: str,
        market_type: str = "spot",
    ) -> dict:
        """Текущий тикер символа."""
        return await self._exchange.get_ticker(symbol, market_type)

    async def get_multi_timeframe(
        self,
        symbol: str,
        timeframes: list[str],
        limit: int = 200,
        market_type: str = "spot",
    ) -> dict[str, pd.DataFrame]:
        """
        Загружает OHLCV сразу для нескольких таймфреймов.

        Returns:
            {"5m": DataFrame, "1h": DataFrame, ...}
        """
        import asyncio

        tasks = {
            tf: self.get_ohlcv_df(symbol, tf, limit, market_type)
            for tf in timeframes
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        output: dict[str, pd.DataFrame] = {}
        for tf, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Ошибка загрузки {symbol} {tf}: {result}")
            else:
                output[tf] = result

        return output

    async def scan_volume_leaders(
        self,
        quote_currency: str = "USDT",
        market_type: str = "spot",
        top_n: int = 30,
        min_quote_volume: float = 1_000_000,
        max_quote_volume: float | None = None,
    ) -> list[dict]:
        """
        Скринер: возвращает топ-N монет по объёму торгов за 24ч.
        Использует fetch_tickers() — один HTTP запрос вместо N.

        Args:
            quote_currency:   котируемая валюта (обычно USDT)
            market_type:      'spot' или 'futures'
            top_n:            сколько монет вернуть
            min_quote_volume: минимальный объём в USDT за 24ч (0 = без ограничения)
            max_quote_volume: максимальный объём в USDT за 24ч (None = без ограничения)
                              используется для поиска неликвидных монет (< 2M$)

        Returns:
            Список словарей с тикером каждой монеты
        """
        client = self._exchange._client(market_type)

        # Один запрос — все тикеры сразу (Gate.io поддерживает batch endpoint)
        try:
            raw_tickers = await client.fetch_tickers()
        except Exception as e:
            logger.error(f"fetch_tickers() провалился: {e}")
            raw_tickers = {}

        valid: list[dict] = []
        for symbol, t in raw_tickers.items():
            # Фильтр по котируемой валюте
            # Спот: "BTC/USDT", фьючерсы: "BTC/USDT:USDT" — берём часть до ":"
            base_symbol = symbol.split(":")[0]
            if not base_symbol.endswith(f"/{quote_currency}"):
                continue
            quote_vol = t.get("quoteVolume") or 0
            if quote_vol < min_quote_volume:
                continue
            if max_quote_volume is not None and quote_vol >= max_quote_volume:
                continue
            last = t.get("last") or 0
            if not last:
                continue  # монета без цены — игнорируем
            valid.append({
                "symbol":         t["symbol"],
                "last":           last,
                "bid":            t.get("bid") or 0,
                "ask":            t.get("ask") or 0,
                "volume_24h":     t.get("baseVolume") or 0,
                "quote_vol_24h":  quote_vol,
                "change_24h_pct": t.get("percentage"),
                "high_24h":       t.get("high"),
                "low_24h":        t.get("low"),
            })

        valid.sort(key=lambda x: x["quote_vol_24h"], reverse=True)

        logger.info(
            f"Скринер завершён | {market_type} | "
            f"всего тикеров: {len(raw_tickers)} | "
            f"прошли фильтр: {len(valid)} | "
            f"топ: {top_n}"
        )
        return valid[:top_n]
