from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.database import get_today_stats, update_daily_pnl
from core.config import config
from data.market_data import MarketDataService
from data.orderbook import OrderBookAnalyzer
from analysis.technical import signals as ta_signals
from risk import calculator as risk_calc
from web.app import get_exchange

router = APIRouter(tags=["market"])


# ── Схемы ответов ────────────────────────────────────────────────────────────

class TickerResponse(BaseModel):
    symbol: str
    last: float
    bid: float
    ask: float
    volume_24h: float
    quote_vol_24h: float
    change_24h_pct: float | None
    high_24h: float | None
    low_24h: float | None


class OrderBookResponse(BaseModel):
    symbol: str
    market_type: str
    best_bid: float
    best_ask: float
    spread: float
    spread_pct: float
    is_liquid: bool
    bid_volume: float
    ask_volume: float
    pressure: str
    pressure_ratio: float
    support_levels: list
    resistance_levels: list
    verdict: str


class StatsResponse(BaseModel):
    trade_date: str
    realized_pnl: float
    trades_count: int
    losses_count: int
    session_blocked: bool
    remaining: float
    used_pct: float


# ── Эндпоинты ────────────────────────────────────────────────────────────────

class RecordTradeRequest(BaseModel):
    pnl: float = Field(description="Результат сделки в USDT (положительный = прибыль, отрицательный = убыток)")


@router.post("/pnl")
async def record_trade(req: RecordTradeRequest):
    """Записывает результат закрытой сделки в дневную статистику."""
    try:
        updated = update_daily_pnl(req.pnl)
        limit = config.DAILY_DRAWDOWN_LIMIT
        pnl = updated["realized_pnl"]
        return {
            **updated,
            "session_blocked": bool(updated["session_blocked"]),
            "remaining": round(limit + pnl, 2),
            "used_pct":  round(min(abs(pnl) / limit * 100, 100) if pnl < 0 else 0, 1),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Дневная статистика (для polling с фронтенда)."""
    s = get_today_stats()
    pnl = s["realized_pnl"]
    limit = config.DAILY_DRAWDOWN_LIMIT
    used_pct = min(abs(pnl) / limit * 100, 100) if pnl < 0 else 0
    return {
        **s,
        "session_blocked": bool(s["session_blocked"]),
        "remaining": round(limit + pnl, 2),
        "used_pct": round(used_pct, 1),
    }


@router.get("/ticker", response_model=TickerResponse)
async def get_ticker(
    symbol: str = Query(default="BTC/USDT"),
    market: str = Query(default="spot"),
):
    exchange = get_exchange()
    try:
        svc = MarketDataService(exchange)
        t = await svc.get_ticker(symbol, market)
        return {**t, "volume_24h": t.get("volume_24h", 0)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")


@router.get("/orderbook", response_model=OrderBookResponse)
async def get_orderbook(
    symbol: str = Query(default="BTC/USDT"),
    market: str = Query(default="spot"),
    depth: int = Query(default=20, ge=5, le=100),
):
    exchange = get_exchange()
    try:
        analyzer = OrderBookAnalyzer(exchange)
        analysis = await analyzer.analyze(symbol, depth, market)
        verdict = analyzer.liquidity_verdict(analysis)
        return {**analysis, "verdict": verdict}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")


@router.get("/ta")
async def get_ta(
    symbol: str = Query(default="BTC/USDT"),
    market: str = Query(default="spot"),
    timeframe: str = Query(default="5m"),
    limit: int = Query(default=200, ge=50, le=1000),
):
    """
    Технический анализ символа: индикаторы + паттерны + уровни + сигнал.
    Также возвращает расчёт риска для точки входа.
    """
    exchange = get_exchange()
    try:
        svc = MarketDataService(exchange)
        df  = await svc.get_ohlcv_df(symbol, timeframe, limit, market)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")

    signal = ta_signals.generate(df, timeframe)

    # Расчёт риска для текущей цены
    ind  = signal.get("indicators", {})
    near = signal.get("nearest", {})
    atr  = ind.get("atr")
    sup  = near.get("nearest_support",    [{}])[0].get("price") if near.get("nearest_support")    else None
    res  = near.get("nearest_resistance", [{}])[0].get("price") if near.get("nearest_resistance") else None

    entry_price = ind.get("close", 0)
    direction   = signal["direction"] if signal["direction"] != "neutral" else "long"

    setup = risk_calc.calculate(
        direction           = direction,
        entry_price         = entry_price,
        atr                 = atr,
        nearest_support     = sup,
        nearest_resistance  = res,
    )

    return {
        "symbol":    symbol,
        "market":    market,
        "timeframe": timeframe,
        "signal":    signal,
        "risk":      risk_calc.to_dict(setup),
    }


ILLIQUID_MAX_VOLUME = 2_000_000   # монеты с оборотом < 2M$ считаются неликвидными


@router.get("/screener")
async def screener(
    market: str      = Query(default="spot"),
    top_n: int       = Query(default=20, ge=5, le=50),
    min_volume: float= Query(default=500_000),
    liquidity: str   = Query(default="all"),   # all / liquid / illiquid
    pattern: str     = Query(default=""),       # "" / bullish / bearish / doji / hammer / ...
    timeframe: str   = Query(default="1h"),
):
    """
    Скринер монет с расширенными фильтрами.
    - liquidity: all | liquid (volume>=2M$, spread<0.3%) | illiquid (volume<2M$)
    - pattern: "" | bullish | bearish | doji | hammer | engulfing | marubozu | ...
    """
    import asyncio

    exchange = get_exchange()
    try:
        svc = MarketDataService(exchange)

        if liquidity == "illiquid":
            # Неликвиды: объём < 2M$, минимальный порог = 10K$ (отсеиваем мёртвые монеты)
            leaders = await svc.scan_volume_leaders(
                market_type=market,
                top_n=top_n,
                min_quote_volume=10_000,
                max_quote_volume=ILLIQUID_MAX_VOLUME,
            )
        else:
            leaders = await svc.scan_volume_leaders(
                market_type=market,
                top_n=top_n,
                min_quote_volume=min_volume,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка скринера: {e}")

    # ── Фильтр ликвидных (доп. проверка спреда через стакан) ─────────────────
    if liquidity == "liquid":
        from data.orderbook import OrderBookAnalyzer
        analyzer = OrderBookAnalyzer(exchange)

        async def check_liquid(sym: str) -> dict | None:
            try:
                ob = await analyzer.analyze(sym, 10, market)
                spread_pct = ob.get("spread_pct", 0)
                return {"spread_pct": round(spread_pct, 4)} if spread_pct <= 0.3 else None
            except Exception:
                return None

        tasks = [check_liquid(t["symbol"]) for t in leaders]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        leaders = [
            {**coin, "spread_pct": res["spread_pct"]}
            for coin, res in zip(leaders, results)
            if isinstance(res, dict)
        ]

    # ── Фильтр по ТА паттернам ────────────────────────────────────────────────
    if pattern:
        from analysis.technical.patterns import detect as detect_patterns

        DIRECTION_MAP = {
            "bullish":      ("bullish",),
            "bearish":      ("bearish",),
            "doji":         None,   # special — check pattern name
            "hammer":       None,
            "engulfing":    None,
            "marubozu":     None,
            "shooting_star":None,
            "morning_star": None,
            "evening_star": None,
        }

        async def check_pattern(coin: dict) -> dict | None:
            try:
                df = await svc.get_ohlcv_df(coin["symbol"], timeframe, 100, market)
                found = detect_patterns(df, n_candles=5)
                if not found:
                    return None

                if pattern in ("bullish", "bearish"):
                    direction = pattern
                    matched = [p for p in found if p["direction"] == direction]
                else:
                    matched = [p for p in found if pattern.lower() in p["pattern"].lower().replace(" ", "_")]

                if not matched:
                    return None

                top = max(matched, key=lambda x: x.get("strength", 0))
                return {"matched_pattern": top["pattern"], "direction": top["direction"]}
            except Exception:
                return None

        # Батчами по 5 чтобы не перегружать API
        enriched = []
        batch_size = 5
        for i in range(0, len(leaders), batch_size):
            batch = leaders[i:i+batch_size]
            results = await asyncio.gather(*[check_pattern(c) for c in batch], return_exceptions=True)
            for coin, res in zip(batch, results):
                if isinstance(res, dict):
                    enriched.append({**coin, **res})

        leaders = enriched

    return {"data": leaders, "count": len(leaders)}
