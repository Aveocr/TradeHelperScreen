from __future__ import annotations

import asyncio
from typing import Optional

import ccxt.async_support as ccxt

from core.config import config
from core.logger import get_logger
from exchanges.base import BaseExchange

logger = get_logger(__name__)


class GateExchange(BaseExchange):
    """
    Коннектор к Gate.io через ccxt (async).
    Поддерживает спот и фьючерсы (Gate Futures USD-M).
    """

    # Поддерживаемые таймфреймы Gate.io
    SUPPORTED_TIMEFRAMES = {
        "1m", "5m", "15m", "30m",
        "1h", "4h", "8h", "1d", "1w",
    }

    def __init__(self) -> None:
        self._spot: ccxt.gateio = ccxt.gateio({
            "apiKey": config.GATE_API_KEY,
            "secret": config.GATE_API_SECRET,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        })

        self._futures: ccxt.gateio = ccxt.gateio({
            "apiKey": config.GATE_API_KEY,
            "secret": config.GATE_API_SECRET,
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self, market_type: str = "spot") -> ccxt.gateio:
        return self._futures if market_type == "futures" else self._spot

    @staticmethod
    def _validate_timeframe(timeframe: str) -> None:
        if timeframe not in GateExchange.SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Неподдерживаемый таймфрейм '{timeframe}'. "
                f"Доступные: {sorted(GateExchange.SUPPORTED_TIMEFRAMES)}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        limit: int = 200,
        market_type: str = "spot",
    ) -> list[dict]:
        """
        Возвращает список OHLCV свечей.

        Args:
            symbol:      торговая пара, напр. 'BTC/USDT'
            timeframe:   '1m', '5m', '15m', '1h', '4h' и т.д.
            limit:       количество свечей (макс. 1000)
            market_type: 'spot' или 'futures'
        """
        self._validate_timeframe(timeframe)
        client = self._client(market_type)

        try:
            raw = await client.fetch_ohlcv(symbol, timeframe, limit=limit)
        except ccxt.BadSymbol:
            raise ValueError(f"Символ '{symbol}' не найден на Gate.io ({market_type})")
        except ccxt.NetworkError as e:
            logger.error(f"Сетевая ошибка при получении OHLCV {symbol}: {e}")
            raise

        return [
            {
                "timestamp": candle[0],
                "open":   candle[1],
                "high":   candle[2],
                "low":    candle[3],
                "close":  candle[4],
                "volume": candle[5],
            }
            for candle in raw
        ]

    async def get_ticker(
        self,
        symbol: str,
        market_type: str = "spot",
    ) -> dict:
        """Текущий тикер символа."""
        client = self._client(market_type)

        try:
            t = await client.fetch_ticker(symbol)
        except ccxt.BadSymbol:
            raise ValueError(f"Символ '{symbol}' не найден на Gate.io ({market_type})")

        return {
            "symbol":        t["symbol"],
            "last":          t["last"],
            "bid":           t["bid"],
            "ask":           t["ask"],
            "volume_24h":    t["baseVolume"],
            "quote_vol_24h": t["quoteVolume"],
            "change_24h_pct": t["percentage"],
            "high_24h":      t["high"],
            "low_24h":       t["low"],
        }

    async def get_orderbook(
        self,
        symbol: str,
        depth: int = 20,
        market_type: str = "spot",
    ) -> dict:
        """
        Стакан заявок.

        Returns:
            {"bids": [[price, size], ...], "asks": [[price, size], ...],
             "spread": float, "spread_pct": float}
        """
        client = self._client(market_type)

        try:
            ob = await client.fetch_order_book(symbol, limit=depth)
        except ccxt.BadSymbol:
            raise ValueError(f"Символ '{symbol}' не найден на Gate.io ({market_type})")

        bids = ob["bids"]
        asks = ob["asks"]

        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        spread = round(best_ask - best_bid, 8)
        spread_pct = round(spread / best_ask * 100, 4) if best_ask else 0.0

        return {
            "bids":       bids,
            "asks":       asks,
            "best_bid":   best_bid,
            "best_ask":   best_ask,
            "spread":     spread,
            "spread_pct": spread_pct,
        }

    async def get_markets(
        self,
        market_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Список активных рынков Gate.io.

        Args:
            market_type: 'spot' | 'futures' | None (оба)
        """
        results: list[dict] = []

        async def _fetch(mtype: str) -> None:
            client = self._client(mtype)
            await client.load_markets()
            for symbol, info in client.markets.items():
                if not info.get("active"):
                    continue
                results.append({
                    "symbol":      symbol,
                    "base":        info["base"],
                    "quote":       info["quote"],
                    "market_type": mtype,
                    "min_amount":  info.get("limits", {}).get("amount", {}).get("min"),
                    "precision":   info.get("precision", {}),
                })

        if market_type in (None, "spot"):
            await _fetch("spot")
        if market_type in (None, "futures"):
            await _fetch("futures")

        return results

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Trading: positions, balances, orders
    # ------------------------------------------------------------------

    async def get_balance(self, market_type: str = "spot") -> dict:
        """
        Полный баланс аккаунта (включая USDT).

        Returns:
            {"free": {currency: amount}, "total": {currency: amount},
             "usdt_free": float, "usdt_total": float}
        """
        client = self._client(market_type)
        try:
            raw = await client.fetch_balance()
        except Exception as e:
            logger.error(f"Ошибка получения баланса ({market_type}): {e}")
            raise

        free  = {k: v for k, v in raw.get("free",  {}).items() if v and v > 0}
        total = {k: v for k, v in raw.get("total", {}).items() if v and v > 0}

        return {
            "free":        free,
            "total":       total,
            "usdt_free":   raw.get("free",  {}).get("USDT", 0) or 0,
            "usdt_total":  raw.get("total", {}).get("USDT", 0) or 0,
        }

    async def get_positions(self, market_type: str = "futures") -> list[dict]:
        """
        Открытые позиции (только фьючерсы).
        Для спота возвращает ненулевые балансы с текущей ценой.
        """
        client = self._client(market_type)

        if market_type == "futures":
            try:
                raw = await client.fetch_positions()
            except Exception as e:
                logger.error(f"Ошибка получения позиций: {e}")
                return []

            result = []
            for p in raw:
                contracts = p.get("contracts") or p.get("contractSize") or 0
                if not contracts:
                    continue
                side = p.get("side", "long")
                entry = p.get("entryPrice") or p.get("averagePrice") or 0
                mark  = p.get("markPrice") or p.get("lastPrice") or entry
                pnl   = p.get("unrealizedPnl") or 0
                pnl_pct = ((mark - entry) / entry * 100) if entry else 0
                if side == "short":
                    pnl_pct = -pnl_pct
                result.append({
                    "symbol":     p.get("symbol", ""),
                    "side":       side,
                    "contracts":  float(contracts),
                    "notional":   float(p.get("notional") or p.get("initialMargin") or 0),
                    "entry_price": float(entry),
                    "mark_price":  float(mark),
                    "pnl":        float(pnl),
                    "pnl_pct":    round(float(pnl_pct), 2),
                    "liq_price":  float(p.get("liquidationPrice") or 0),
                    "leverage":   float(p.get("leverage") or 1),
                    "market_type": "futures",
                })
            return result

        else:
            # Spot: возвращаем ненулевые балансы
            try:
                balance = await client.fetch_balance()
            except Exception as e:
                logger.error(f"Ошибка получения баланса: {e}")
                return []

            result = []
            for currency, data in balance.get("total", {}).items():
                if currency in ("USDT", "USD") or not data or data <= 0:
                    continue
                symbol = f"{currency}/USDT"
                try:
                    ticker = await self._spot.fetch_ticker(symbol)
                    last = ticker.get("last") or 0
                    value = data * last
                    if value < 1.0:  # игнорируем позиции менее $1
                        continue
                    result.append({
                        "symbol":      symbol,
                        "side":        "long",
                        "contracts":   float(data),
                        "notional":    float(value),
                        "entry_price": 0.0,  # неизвестно для спота
                        "mark_price":  float(last),
                        "pnl":         0.0,
                        "pnl_pct":     0.0,
                        "liq_price":   0.0,
                        "leverage":    1.0,
                        "market_type": "spot",
                    })
                except Exception:
                    pass
            return result

    async def place_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float | None = None,
        order_type: str = "limit",
        market_type: str = "spot",
    ) -> dict:
        """
        Размещает ордер.

        Args:
            symbol:     торговая пара, напр. 'BTC/USDT'
            side:       'buy' или 'sell'
            amount:     количество базовой валюты
            price:      цена (для limit-ордера)
            order_type: 'limit' или 'market'
            market_type:'spot' или 'futures'
        """
        client = self._client(market_type)
        try:
            if order_type == "market":
                order = await client.create_market_order(symbol, side, amount)
            else:
                if price is None:
                    raise ValueError("Для лимитного ордера необходима цена")
                order = await client.create_limit_order(symbol, side, amount, price)

            return {
                "id":     order.get("id"),
                "symbol": order.get("symbol"),
                "side":   order.get("side"),
                "type":   order.get("type"),
                "amount": order.get("amount"),
                "price":  order.get("price"),
                "status": order.get("status"),
            }
        except Exception as e:
            logger.error(f"Ошибка размещения ордера {symbol}: {e}")
            raise

    async def close_position_market(
        self,
        symbol: str,
        side: str,
        amount: float,
        market_type: str = "futures",
    ) -> dict:
        """
        Закрывает позицию по рынку.
        Для long → sell market, для short → buy market.
        """
        close_side = "sell" if side == "long" else "buy"
        return await self.place_order(
            symbol=symbol,
            side=close_side,
            amount=amount,
            order_type="market",
            market_type=market_type,
        )

    async def get_open_orders(
        self,
        symbol: str | None = None,
        market_type: str = "spot",
    ) -> list[dict]:
        """Открытые ордера по символу (или все)."""
        client = self._client(market_type)
        try:
            raw = await client.fetch_open_orders(symbol)
            return [
                {
                    "id":         o.get("id"),
                    "symbol":     o.get("symbol"),
                    "side":       o.get("side"),
                    "type":       o.get("type"),
                    "amount":     o.get("amount"),
                    "price":      o.get("price"),
                    "filled":     o.get("filled"),
                    "remaining":  o.get("remaining"),
                    "status":     o.get("status"),
                    "timestamp":  o.get("timestamp"),
                }
                for o in raw
            ]
        except Exception as e:
            logger.error(f"Ошибка получения открытых ордеров: {e}")
            return []

    async def cancel_order(
        self,
        order_id: str,
        symbol: str,
        market_type: str = "spot",
    ) -> dict:
        """Отменяет ордер по ID."""
        client = self._client(market_type)
        try:
            result = await client.cancel_order(order_id, symbol)
            return {"id": result.get("id"), "status": result.get("status", "canceled")}
        except Exception as e:
            logger.error(f"Ошибка отмены ордера {order_id}: {e}")
            raise

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        await asyncio.gather(
            self._spot.close(),
            self._futures.close(),
            return_exceptions=True,
        )
        logger.debug("Gate.io соединения закрыты")
