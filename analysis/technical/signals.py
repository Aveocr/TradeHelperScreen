"""
Генератор торговых сигналов.
Агрегирует показания индикаторов, паттернов и уровней
в итоговый сигнал с направлением и силой.
"""

from __future__ import annotations

import pandas as pd

from analysis.technical import indicators, patterns, levels
from core.logger import get_logger

logger = get_logger(__name__)


def generate(
    df: pd.DataFrame,
    timeframe: str = "5m",
) -> dict:
    """
    Полный технический анализ DataFrame.

    Returns:
        {
            "direction":  "long" | "short" | "neutral",
            "score":      int,        # -100..+100 (положительный = bullish)
            "confidence": "high" | "medium" | "low",
            "timeframe":  str,
            "indicators": dict,       # последние значения индикаторов
            "patterns":   list[dict], # найденные паттерны
            "levels":     dict,       # поддержки / сопротивления
            "range":      dict,       # текущий диапазон
            "reasons":    list[str],  # текстовые обоснования
        }
    """
    if len(df) < 50:
        return _empty_signal(timeframe, "Недостаточно свечей для анализа")

    # 1. Индикаторы
    df_ind  = indicators.compute_all(df)
    ind     = indicators.get_last(df_ind)

    # 2. Паттерны
    found_patterns = patterns.detect(df, lookback=5)

    # 3. Уровни
    lvls  = levels.find_pivot_levels(df)
    rng   = levels.find_range(df)
    near  = levels.nearest_levels(lvls, ind["close"])

    # 4. Скоринг
    score, reasons = _score(ind, found_patterns, near, rng)

    # 5. Итоговый сигнал
    if score >= 25:
        direction  = "long"
        confidence = "high" if score >= 50 else "medium"
    elif score <= -25:
        direction  = "short"
        confidence = "high" if score <= -50 else "medium"
    else:
        direction  = "neutral"
        confidence = "low"

    return {
        "direction":  direction,
        "score":      score,
        "confidence": confidence,
        "timeframe":  timeframe,
        "indicators": ind,
        "patterns":   found_patterns,
        "levels":     lvls,
        "nearest":    near,
        "range":      rng,
        "reasons":    reasons,
    }


def _score(
    ind: dict,
    found_patterns: list[dict],
    near: dict,
    rng: dict,
) -> tuple[int, list[str]]:
    """
    Подсчёт скора от -100 до +100.
    Положительный → bullish, отрицательный → bearish.
    """
    score   = 0
    reasons = []

    close = ind.get("close") or 0

    # ── EMA тренд ──────────────────────────────────────────────────────────────
    trend = ind.get("ema_trend")
    if trend == "uptrend":
        score += 20
        reasons.append("EMA 9 > 21 > 50 — восходящий тренд")
    elif trend == "downtrend":
        score -= 20
        reasons.append("EMA 9 < 21 < 50 — нисходящий тренд")

    # Цена выше/ниже EMA 50
    ema50 = ind.get("ema_50")
    if ema50 and close > ema50:
        score += 10
        reasons.append(f"Цена ({close:.4g}) выше EMA 50 ({ema50:.4g})")
    elif ema50 and close < ema50:
        score -= 10
        reasons.append(f"Цена ({close:.4g}) ниже EMA 50 ({ema50:.4g})")

    # ── RSI ────────────────────────────────────────────────────────────────────
    rsi = ind.get("rsi")
    if rsi is not None:
        if rsi < 30:
            score += 20
            reasons.append(f"RSI перепродан ({rsi:.1f})")
        elif rsi < 45:
            score += 8
            reasons.append(f"RSI ниже 45 — слабость продавцов ({rsi:.1f})")
        elif rsi > 70:
            score -= 20
            reasons.append(f"RSI перекуплен ({rsi:.1f})")
        elif rsi > 55:
            score -= 8
            reasons.append(f"RSI выше 55 — давление покупателей ({rsi:.1f})")

    # ── MACD ───────────────────────────────────────────────────────────────────
    macd_cross = ind.get("macd_cross")
    macd_hist  = ind.get("macd_hist")
    if macd_cross == "bullish":
        score += 15
        reasons.append("MACD пересёк сигнальную линию снизу вверх")
    elif macd_cross == "bearish":
        score -= 15
        reasons.append("MACD пересёк сигнальную линию сверху вниз")
    elif macd_hist is not None:
        if macd_hist > 0:
            score += 5
        else:
            score -= 5

    # ── Bollinger Bands ─────────────────────────────────────────────────────────
    bb_pct = ind.get("bb_pct")
    if bb_pct is not None:
        if bb_pct < 0.1:
            score += 12
            reasons.append(f"Цена у нижней полосы Боллинджера (%B={bb_pct:.2f})")
        elif bb_pct > 0.9:
            score -= 12
            reasons.append(f"Цена у верхней полосы Боллинджера (%B={bb_pct:.2f})")

    # ── Stochastic ─────────────────────────────────────────────────────────────
    sk = ind.get("stoch_k")
    sd = ind.get("stoch_d")
    if sk is not None and sd is not None:
        if sk < 20 and sd < 20:
            score += 10
            reasons.append(f"Stochastic в зоне перепроданности (K={sk:.0f})")
        elif sk > 80 and sd > 80:
            score -= 10
            reasons.append(f"Stochastic в зоне перекупленности (K={sk:.0f})")

    # ── VWAP ───────────────────────────────────────────────────────────────────
    vwap = ind.get("vwap")
    if vwap and close:
        if close > vwap:
            score += 5
            reasons.append(f"Цена выше VWAP ({vwap:.4g})")
        else:
            score -= 5
            reasons.append(f"Цена ниже VWAP ({vwap:.4g})")

    # ── Объём ──────────────────────────────────────────────────────────────────
    vol_ratio = ind.get("vol_ratio")
    if vol_ratio and vol_ratio > 1.5:
        reasons.append(f"Объём в {vol_ratio:.1f}× выше среднего — подтверждение движения")

    # ── Паттерны ───────────────────────────────────────────────────────────────
    strength_pts = {"strong": 15, "medium": 8, "weak": 3}
    for p in found_patterns:
        pts = strength_pts.get(p["strength"], 5)
        if p["direction"] == "bullish":
            score += pts
            reasons.append(f"Паттерн: {p['pattern']} (бычий, {p['strength']})")
        elif p["direction"] == "bearish":
            score -= pts
            reasons.append(f"Паттерн: {p['pattern']} (медвежий, {p['strength']})")

    # ── Уровни ─────────────────────────────────────────────────────────────────
    sup_levels = near.get("nearest_support", [])
    res_levels = near.get("nearest_resistance", [])

    if sup_levels:
        closest_sup = sup_levels[0]["price"]
        dist_pct = abs(close - closest_sup) / close * 100
        if dist_pct < 0.5:
            score += 8
            reasons.append(f"Цена у поддержки {closest_sup:.4g} (расстояние {dist_pct:.2f}%)")

    if res_levels:
        closest_res = res_levels[0]["price"]
        dist_pct = abs(closest_res - close) / close * 100
        if dist_pct < 0.5:
            score -= 8
            reasons.append(f"Цена у сопротивления {closest_res:.4g} (расстояние {dist_pct:.2f}%)")

    return max(-100, min(100, score)), reasons


def _empty_signal(timeframe: str, reason: str) -> dict:
    return {
        "direction":  "neutral",
        "score":      0,
        "confidence": "low",
        "timeframe":  timeframe,
        "indicators": {},
        "patterns":   [],
        "levels":     {"support": [], "resistance": []},
        "nearest":    {"nearest_support": [], "nearest_resistance": []},
        "range":      {},
        "reasons":    [reason],
    }
