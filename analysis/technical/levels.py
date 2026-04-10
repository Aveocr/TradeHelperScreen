"""
Поиск уровней поддержки и сопротивления через локальные экстремумы и кластеризацию.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def find_pivot_levels(
    df: pd.DataFrame,
    left: int = 5,
    right: int = 5,
    max_levels: int = 6,
    merge_pct: float = 0.003,
) -> dict[str, list[dict]]:
    """
    Находит уровни поддержки и сопротивления через pivot-точки (локальные экстремумы).

    Args:
        df:          OHLCV DataFrame
        left:        сколько свечей слева от pivot
        right:       сколько свечей справа от pivot
        max_levels:  максимум уровней каждого типа
        merge_pct:   порог слияния близких уровней (0.3% по умолчанию)

    Returns:
        {"support": [...], "resistance": [...]}
        Каждый уровень: {"price": float, "touches": int, "strength": str}
    """
    highs = df["high"].values
    lows  = df["low"].values
    n     = len(df)

    pivot_highs: list[float] = []
    pivot_lows:  list[float] = []

    for i in range(left, n - right):
        window_h = highs[i - left: i + right + 1]
        window_l = lows[i - left: i + right + 1]
        if highs[i] == max(window_h):
            pivot_highs.append(highs[i])
        if lows[i] == min(window_l):
            pivot_lows.append(lows[i])

    support    = _cluster_levels(pivot_lows,  merge_pct, max_levels)
    resistance = _cluster_levels(pivot_highs, merge_pct, max_levels)

    # Фильтруем: поддержка ниже текущей цены, сопротивление выше
    current = float(df["close"].iloc[-1])
    support    = [l for l in support    if l["price"] <= current * 1.005]
    resistance = [l for l in resistance if l["price"] >= current * 0.995]

    # Сортировка: поддержки по убыванию (ближайшая первой), сопротивления по возрастанию
    support.sort(key=lambda x: x["price"], reverse=True)
    resistance.sort(key=lambda x: x["price"])

    return {"support": support[:max_levels], "resistance": resistance[:max_levels]}


def _cluster_levels(
    prices: list[float],
    merge_pct: float,
    max_levels: int,
) -> list[dict]:
    """Кластеризует близкие уровни в один, считает количество касаний."""
    if not prices:
        return []

    prices_sorted = sorted(prices)
    clusters: list[list[float]] = []

    for p in prices_sorted:
        merged = False
        for cluster in clusters:
            if abs(p - cluster[0]) / cluster[0] < merge_pct:
                cluster.append(p)
                merged = True
                break
        if not merged:
            clusters.append([p])

    result = []
    for cluster in clusters:
        avg     = float(np.mean(cluster))
        touches = len(cluster)
        if touches >= 3:
            strength = "strong"
        elif touches == 2:
            strength = "medium"
        else:
            strength = "weak"
        result.append({"price": round(avg, 8), "touches": touches, "strength": strength})

    # Сортируем по количеству касаний (сильнейшие первые)
    result.sort(key=lambda x: x["touches"], reverse=True)
    return result[:max_levels]


def nearest_levels(
    levels: dict[str, list[dict]],
    current_price: float,
    n: int = 2,
) -> dict:
    """
    Возвращает N ближайших уровней поддержки и сопротивления к текущей цене.
    Используется для расчёта TP и SL.
    """
    sup = sorted(
        [l for l in levels["support"] if l["price"] < current_price],
        key=lambda x: current_price - x["price"],
    )[:n]

    res = sorted(
        [l for l in levels["resistance"] if l["price"] > current_price],
        key=lambda x: x["price"] - current_price,
    )[:n]

    return {"nearest_support": sup, "nearest_resistance": res}


def find_range(df: pd.DataFrame, period: int = 20) -> dict:
    """
    Текущий торговый диапазон за последние `period` свечей.
    Используется для оценки волатильности и ATR-зон.
    """
    recent = df.tail(period)
    high   = float(recent["high"].max())
    low    = float(recent["low"].min())
    mid    = (high + low) / 2
    width  = high - low
    width_pct = width / mid * 100 if mid else 0

    return {
        "high":      round(high, 8),
        "low":       round(low, 8),
        "mid":       round(mid, 8),
        "width":     round(width, 8),
        "width_pct": round(width_pct, 2),
    }
