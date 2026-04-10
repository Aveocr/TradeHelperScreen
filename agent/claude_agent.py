"""
Claude AI агент — ядро рекомендательной системы.
Принимает рыночные данные + ТА + сентимент и генерирует торговую рекомендацию.
"""

from __future__ import annotations

import anthropic

from core.config import config
from core.logger import get_logger
from agent.prompts import SYSTEM_TRADING, SYSTEM_SESSION

logger = get_logger(__name__)


class TradingAgent:
    """
    Обёртка над Claude API для генерации торговых рекомендаций.
    Использует streaming для потоковой передачи ответа в веб-интерфейс.
    """

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def _system_prompt(self) -> str:
        return SYSTEM_TRADING.format(
            entry_size  = config.ENTRY_SIZE,
            max_loss    = config.MAX_LOSS_PER_TRADE,
            rr_ratio    = int(config.MIN_RR_RATIO),
            tp1         = config.MAX_LOSS_PER_TRADE * 3,
            tp2         = config.MAX_LOSS_PER_TRADE * 5,
            tp3         = config.MAX_LOSS_PER_TRADE * 8,
            daily_limit = config.DAILY_DRAWDOWN_LIMIT,
        )

    # ── Рекомендация по сделке ────────────────────────────────────────────────

    def build_trade_context(
        self,
        symbol:     str,
        market:     str,
        timeframe:  str,
        ticker:     dict,
        signal:     dict,
        risk:       dict,
        sentiment:  dict | None = None,
        ob:         dict | None = None,
    ) -> str:
        """Формирует текст контекста для Claude из всех источников данных."""
        ind  = signal.get("indicators", {})
        lvls = signal.get("nearest", {})

        sup_prices = [str(l["price"]) for l in lvls.get("nearest_support",    [])[:2]]
        res_prices = [str(l["price"]) for l in lvls.get("nearest_resistance", [])[:2]]

        patterns_str = (
            ", ".join(f"{p['pattern']} ({p['direction']})"
                      for p in signal.get("patterns", []))
            or "паттернов не обнаружено"
        )

        reasons_str = "\n".join(f"  - {r}" for r in signal.get("reasons", []))

        sentiment_str = ""
        if sentiment and not sentiment.get("error"):
            sentiment_str = f"""
СЕНТИМЕНТ REDDIT:
  Скор: {sentiment['score']} ({sentiment['label'].upper()})
  Постов за 24ч: {sentiment['sources']['reddit']['total_posts']}
  Бычьих: {sentiment['sources']['reddit']['bullish_count']}  Медвежьих: {sentiment['sources']['reddit']['bearish_count']}
  Топ обсуждения: {chr(10).join('  • ' + t for t in sentiment['sources']['reddit']['top_titles'][:3])}"""

        ob_str = ""
        if ob:
            ob_str = f"""
СТАКАН:
  Ликвидность: {'✓ OK' if ob.get('is_liquid') else '✗ Неликвидно'}  Спред: {ob.get('spread_pct')}%
  Давление: {ob.get('pressure', '—').upper()}  Ratio: {ob.get('pressure_ratio')}"""

        return f"""АНАЛИЗ СИМВОЛА: {symbol} | {market.upper()} | {timeframe}

ТЕКУЩАЯ ЦЕНА: {ticker.get('last')}$
  Изм. 24ч: {ticker.get('change_24h_pct', 0):+.2f}%  Объём 24ч: {ticker.get('quote_vol_24h', 0):,.0f}$
{ob_str}

ТЕХНИЧЕСКИЙ АНАЛИЗ:
  Сигнал: {signal['direction'].upper()}  Скор: {signal['score']}  Уверенность: {signal['confidence'].upper()}
  EMA тренд: {ind.get('ema_trend', '—')}
  RSI: {ind.get('rsi', '—')}  Stoch K/D: {ind.get('stoch_k', '—')}/{ind.get('stoch_d', '—')}
  MACD hist: {ind.get('macd_hist', '—')}  Пересечение: {ind.get('macd_cross', '—')}
  BB %B: {ind.get('bb_pct', '—')}  ATR: {ind.get('atr', '—')} ({ind.get('atr_pct', '—')}%)
  VWAP: {ind.get('vwap', '—')}  Объём ×avg: {ind.get('vol_ratio', '—')}
  Паттерны: {patterns_str}
  Причины сигнала:
{reasons_str}

УРОВНИ:
  Ближайшие поддержки:    {', '.join(sup_prices) or '—'}
  Ближайшие сопротивления: {', '.join(res_prices) or '—'}
{sentiment_str}

РАСЧЁТ РИСКА (предварительный):
  Вход: {risk.get('entry_price')}$  SL: {risk.get('sl_price')}$ (-{risk.get('sl_pct')}%)
  TP1: {risk.get('tp1_price')}$  TP2: {risk.get('tp2_price')}$  TP3: {risk.get('tp3_price')}$
  Размер: {risk.get('entry_size')}$  Макс. убыток: {risk.get('max_loss')}$

На основе этих данных сделай полный анализ и дай торговую рекомендацию."""

    def analyze(
        self,
        context: str,
        stream: bool = False,
    ) -> str:
        """
        Синхронный запрос к Claude.
        stream=True для потоковой передачи (используется в SSE эндпоинте).
        """
        if stream:
            raise ValueError("Для стриминга используй analyze_stream()")

        response = self._client.messages.create(
            model      = config.CLAUDE_MODEL,
            max_tokens = 1500,
            system     = self._system_prompt(),
            messages   = [{"role": "user", "content": context}],
        )
        return response.content[0].text

    def analyze_stream(self, context: str):
        """
        Генератор для потоковой передачи ответа.
        Используется в SSE-эндпоинте FastAPI.
        Yields: строки текста по мере генерации.
        """
        with self._client.messages.stream(
            model      = config.CLAUDE_MODEL,
            max_tokens = 1500,
            system     = self._system_prompt(),
            messages   = [{"role": "user", "content": context}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    # ── Пре-сессионный чек ────────────────────────────────────────────────────

    def session_check(
        self,
        emotional_score: int,
        user_notes: str,
        pnl: float,
        trades: int,
    ) -> str:
        """
        Генерирует персональный совет перед торговой сессией на основе
        эмоционального состояния трейдера и дневной статистики.
        """
        system = SYSTEM_SESSION.format(
            daily_limit = config.DAILY_DRAWDOWN_LIMIT,
            pnl         = f"{pnl:+.2f}",
            trades      = trades,
        )

        user_msg = f"""Моё эмоциональное состояние сегодня: {emotional_score}/10

{f'Заметки: {user_notes}' if user_notes else ''}

Дай оценку и рекомендации — стоит ли мне торговать сегодня?"""

        response = self._client.messages.create(
            model      = config.CLAUDE_MODEL,
            max_tokens = 600,
            system     = system,
            messages   = [{"role": "user", "content": user_msg}],
        )
        return response.content[0].text


# Singleton
_agent: TradingAgent | None = None


def get_agent() -> TradingAgent:
    global _agent
    if _agent is None:
        _agent = TradingAgent()
    return _agent
