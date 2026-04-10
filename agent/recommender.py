"""
Оркестратор рекомендаций.
Собирает данные из всех источников и запускает Claude.
"""

from __future__ import annotations

from core.database import get_conn
from core.logger import get_logger

logger = get_logger(__name__)


async def build_recommendation(
    symbol:    str,
    market:    str,
    timeframe: str,
    exchange,
) -> dict:
    """
    Полный пайплайн:
      1. Тикер + стакан
      2. OHLCV → ТА (сигнал + уровни + паттерны)
      3. Расчёт риска
      4. Reddit сентимент
      5. Claude рекомендация

    Returns: словарь с полными данными для API и фронтенда
    """
    import asyncio

    from data.market_data import MarketDataService
    from data.orderbook import OrderBookAnalyzer
    from analysis.technical import signals as ta_signals
    from analysis.sentiment.reddit import fetch_sentiment, to_dict as sent_to_dict
    from analysis.sentiment.scorer import aggregate as sent_aggregate, from_ta_signal as sent_from_ta
    from risk import calculator as risk_calc
    from agent.claude_agent import get_agent

    svc      = MarketDataService(exchange)
    analyzer = OrderBookAnalyzer(exchange)

    # Параллельно: тикер + стакан + OHLCV + Reddit
    ticker_task  = svc.get_ticker(symbol, market)
    ob_task      = analyzer.analyze(symbol, 20, market)
    ohlcv_task   = svc.get_ohlcv_df(symbol, timeframe, 200, market)
    reddit_task  = fetch_sentiment(symbol)

    ticker, ob, df, reddit = await asyncio.gather(
        ticker_task, ob_task, ohlcv_task, reddit_task,
        return_exceptions=True,
    )

    # Обработка ошибок
    if isinstance(ticker, Exception): raise ticker
    if isinstance(ob,     Exception): ob = None
    if isinstance(df,     Exception): raise df

    # TA + сигнал
    signal = ta_signals.generate(df, timeframe)

    # Риск
    ind  = signal.get("indicators", {})
    near = signal.get("nearest", {})
    atr  = ind.get("atr")
    sup  = near.get("nearest_support",    [{}])[0].get("price") if near.get("nearest_support")    else None
    res  = near.get("nearest_resistance", [{}])[0].get("price") if near.get("nearest_resistance") else None

    setup = risk_calc.calculate(
        direction           = signal["direction"] if signal["direction"] != "neutral" else "long",
        entry_price         = ind.get("close", 0),
        atr                 = atr,
        nearest_support     = sup,
        nearest_resistance  = res,
    )
    risk = risk_calc.to_dict(setup)

    # Сентимент: Reddit или ТА-фоллбэк
    reddit_ok = not isinstance(reddit, Exception) and not getattr(reddit, "error", None)
    if reddit_ok:
        sentiment_data = sent_to_dict(reddit)
        sentiment_agg  = sent_aggregate(reddit)
    else:
        # Reddit недоступен — выводим сентимент из ТА сигнала
        sentiment_data = {"error": str(reddit) if isinstance(reddit, Exception) else getattr(reddit, "error", "Reddit недоступен")}
        sentiment_agg  = sent_from_ta(signal)

    # Claude
    agent   = get_agent()
    context = agent.build_trade_context(
        symbol    = symbol,
        market    = market,
        timeframe = timeframe,
        ticker    = ticker,
        signal    = signal,
        risk      = risk,
        sentiment = sentiment_agg,
        ob        = ob,
    )

    # Запускаем синхронный SDK-вызов в отдельном потоке, не блокируя event loop
    loop = asyncio.get_running_loop()
    claude_text = await loop.run_in_executor(None, agent.analyze, context)

    # Сохраняем рекомендацию в БД
    _save_recommendation(symbol, market, signal, risk, claude_text)

    return {
        "symbol":    symbol,
        "market":    market,
        "timeframe": timeframe,
        "ticker":    ticker,
        "signal":    signal,
        "risk":      risk,
        "sentiment": sentiment_agg,
        "claude":    claude_text,
        "ob":        ob,
    }


def _save_recommendation(
    symbol: str,
    market: str,
    signal: dict,
    risk:   dict,
    text:   str,
) -> None:
    """Сохраняет рекомендацию в таблицу recommendations."""
    if not risk.get("is_valid"):
        return
    direction = signal.get("direction", "neutral")
    if direction == "neutral":
        return
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO recommendations
                   (exchange, symbol, market_type, direction,
                    entry_price, sl_price, tp1_price, tp2_price, tp3_price,
                    entry_size, max_loss, rr_ratio, reasoning)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "gate", symbol, market, direction,
                    risk["entry_price"], risk["sl_price"],
                    risk["tp1_price"], risk["tp2_price"], risk["tp3_price"],
                    risk["entry_size"], risk["max_loss"], risk["rr_ratio"],
                    text[:2000],
                ),
            )
    except Exception as e:
        logger.error(f"Ошибка сохранения рекомендации: {e}")
