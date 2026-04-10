from __future__ import annotations

from core.logger import get_logger
from exchanges.gate import GateExchange

logger = get_logger(__name__)


class OrderBookAnalyzer:
    """
    Анализ стакана заявок для оценки ликвидности и качества точки входа.

    Используется для:
    - Оценки спреда (насколько ликвиден инструмент)
    - Поиска уровней поддержки/сопротивления через кластеры объёма
    - Определения давления покупателей vs продавцов
    """

    # Порог спреда: если спред > N%, инструмент считается неликвидным
    MAX_SPREAD_PCT = 0.3

    def __init__(self, exchange: GateExchange) -> None:
        self._exchange = exchange

    async def analyze(
        self,
        symbol: str,
        depth: int = 20,
        market_type: str = "spot",
    ) -> dict:
        """
        Полный анализ стакана для символа.

        Returns:
            {
                "symbol": str,
                "market_type": str,
                "best_bid": float,
                "best_ask": float,
                "spread": float,
                "spread_pct": float,
                "is_liquid": bool,          # спред ниже порога
                "bid_volume": float,        # суммарный объём в bids
                "ask_volume": float,        # суммарный объём в asks
                "pressure": str,            # "buy" / "sell" / "neutral"
                "pressure_ratio": float,    # bid_vol / ask_vol
                "support_levels": list,     # крупные кластеры в bids
                "resistance_levels": list,  # крупные кластеры в asks
            }
        """
        ob = await self._exchange.get_orderbook(symbol, depth, market_type)

        bids = ob["bids"]  # [[price, size], ...]
        asks = ob["asks"]

        bid_volume = sum(row[1] for row in bids)
        ask_volume = sum(row[1] for row in asks)

        pressure_ratio = round(bid_volume / ask_volume, 3) if ask_volume else 0.0
        if pressure_ratio > 1.15:
            pressure = "buy"
        elif pressure_ratio < 0.87:
            pressure = "sell"
        else:
            pressure = "neutral"

        support_levels = self._find_clusters(bids)
        resistance_levels = self._find_clusters(asks)

        result = {
            "symbol":            symbol,
            "market_type":       market_type,
            "best_bid":          ob["best_bid"],
            "best_ask":          ob["best_ask"],
            "spread":            ob["spread"],
            "spread_pct":        ob["spread_pct"],
            "is_liquid":         ob["spread_pct"] <= self.MAX_SPREAD_PCT,
            "bid_volume":        round(bid_volume, 4),
            "ask_volume":        round(ask_volume, 4),
            "pressure":          pressure,
            "pressure_ratio":    pressure_ratio,
            "support_levels":    support_levels,
            "resistance_levels": resistance_levels,
        }

        logger.debug(
            f"Стакан {symbol} | спред: {ob['spread_pct']}% | "
            f"давление: {pressure} ({pressure_ratio})"
        )
        return result

    @staticmethod
    def _find_clusters(
        orders: list[list[float]],
        top_n: int = 3,
    ) -> list[dict]:
        """
        Находит уровни с наибольшим объёмом в стакане.
        Это потенциальные уровни поддержки (bids) или сопротивления (asks).
        """
        if not orders:
            return []

        sorted_by_vol = sorted(orders, key=lambda x: x[1], reverse=True)
        total_volume = sum(row[1] for row in orders)

        clusters = []
        for price, size in sorted_by_vol[:top_n]:
            clusters.append({
                "price":      price,
                "size":       round(size, 4),
                "volume_pct": round(size / total_volume * 100, 1),
            })

        return sorted(clusters, key=lambda x: x["price"])

    def liquidity_verdict(self, analysis: dict) -> str:
        """
        Текстовый вердикт по ликвидности инструмента.
        Используется агентом при генерации рекомендации.
        """
        if not analysis["is_liquid"]:
            return (
                f"Инструмент НЕЛИКВИДЕН — спред {analysis['spread_pct']}% "
                f"превышает порог {self.MAX_SPREAD_PCT}%. Вход не рекомендован."
            )

        pressure_map = {
            "buy":     "Доминируют покупатели",
            "sell":    "Доминируют продавцы",
            "neutral": "Давление нейтральное",
        }

        return (
            f"Ликвидность OK | спред {analysis['spread_pct']}% | "
            f"{pressure_map[analysis['pressure']]} "
            f"(ratio {analysis['pressure_ratio']})"
        )
