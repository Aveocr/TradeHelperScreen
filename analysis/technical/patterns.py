"""
Распознавание свечных паттернов.
Возвращает найденные паттерны для последних свечей DataFrame.
"""

from __future__ import annotations

import pandas as pd


def _body(row: pd.Series) -> float:
    return abs(row["close"] - row["open"])

def _range(row: pd.Series) -> float:
    return row["high"] - row["low"]

def _upper_shadow(row: pd.Series) -> float:
    return row["high"] - max(row["open"], row["close"])

def _lower_shadow(row: pd.Series) -> float:
    return min(row["open"], row["close"]) - row["low"]

def _is_bullish(row: pd.Series) -> bool:
    return row["close"] > row["open"]

def _is_bearish(row: pd.Series) -> bool:
    return row["close"] < row["open"]


# ── Одиночные паттерны ────────────────────────────────────────────────────────

def is_doji(row: pd.Series, threshold: float = 0.1) -> bool:
    """Доджи: тело < 10% от диапазона."""
    r = _range(row)
    return r > 0 and _body(row) / r < threshold


def is_hammer(row: pd.Series) -> bool:
    """
    Молот (Hammer): бычий разворот.
    - Длинная нижняя тень (≥ 2× тело)
    - Маленькая верхняя тень (≤ 10% диапазона)
    - Встречается после нисходящего тренда
    """
    b = _body(row)
    r = _range(row)
    if b == 0 or r == 0:
        return False
    return (
        _lower_shadow(row) >= 2 * b
        and _upper_shadow(row) <= 0.1 * r
    )


def is_shooting_star(row: pd.Series) -> bool:
    """
    Падающая звезда (Shooting Star): медвежий разворот.
    - Длинная верхняя тень (≥ 2× тело)
    - Маленькая нижняя тень (≤ 10% диапазона)
    """
    b = _body(row)
    r = _range(row)
    if b == 0 or r == 0:
        return False
    return (
        _upper_shadow(row) >= 2 * b
        and _lower_shadow(row) <= 0.1 * r
    )


def is_marubozu_bull(row: pd.Series, threshold: float = 0.05) -> bool:
    """Бычий Марубодзу: почти нет теней, сильное бычье движение."""
    r = _range(row)
    if r == 0:
        return False
    return (
        _is_bullish(row)
        and _upper_shadow(row) / r < threshold
        and _lower_shadow(row) / r < threshold
    )


def is_marubozu_bear(row: pd.Series, threshold: float = 0.05) -> bool:
    """Медвежий Марубодзу: почти нет теней, сильное медвежье движение."""
    r = _range(row)
    if r == 0:
        return False
    return (
        _is_bearish(row)
        and _upper_shadow(row) / r < threshold
        and _lower_shadow(row) / r < threshold
    )


def is_spinning_top(row: pd.Series) -> bool:
    """Волчок: маленькое тело, длинные тени с обеих сторон — нерешительность."""
    b = _body(row)
    r = _range(row)
    if r == 0:
        return False
    return (
        b / r < 0.3
        and _upper_shadow(row) > b
        and _lower_shadow(row) > b
    )


# ── Двухсвечные паттерны ──────────────────────────────────────────────────────

def is_bullish_engulfing(prev: pd.Series, curr: pd.Series) -> bool:
    """
    Бычье поглощение: медвежья свеча полностью перекрыта следующей бычьей.
    """
    return (
        _is_bearish(prev)
        and _is_bullish(curr)
        and curr["open"] <= prev["close"]
        and curr["close"] >= prev["open"]
    )


def is_bearish_engulfing(prev: pd.Series, curr: pd.Series) -> bool:
    """
    Медвежье поглощение: бычья свеча полностью перекрыта следующей медвежьей.
    """
    return (
        _is_bullish(prev)
        and _is_bearish(curr)
        and curr["open"] >= prev["close"]
        and curr["close"] <= prev["open"]
    )


def is_tweezer_bottom(prev: pd.Series, curr: pd.Series, tol: float = 0.001) -> bool:
    """Пинцет снизу: два примерно одинаковых лоя — потенциальный разворот вверх."""
    return (
        _is_bearish(prev)
        and _is_bullish(curr)
        and abs(prev["low"] - curr["low"]) / max(prev["low"], 1e-9) < tol
    )


def is_tweezer_top(prev: pd.Series, curr: pd.Series, tol: float = 0.001) -> bool:
    """Пинцет сверху: два примерно одинаковых хая — потенциальный разворот вниз."""
    return (
        _is_bullish(prev)
        and _is_bearish(curr)
        and abs(prev["high"] - curr["high"]) / max(prev["high"], 1e-9) < tol
    )


# ── Трёхсвечные паттерны ──────────────────────────────────────────────────────

def is_morning_star(c1: pd.Series, c2: pd.Series, c3: pd.Series) -> bool:
    """
    Утренняя звезда: медвежья большая → маленькая → бычья большая.
    Сильный разворотный паттерн.
    """
    return (
        _is_bearish(c1) and _body(c1) > _body(c2)
        and _body(c2) < _body(c1) * 0.4
        and _is_bullish(c3)
        and c3["close"] > (c1["open"] + c1["close"]) / 2
    )


def is_evening_star(c1: pd.Series, c2: pd.Series, c3: pd.Series) -> bool:
    """
    Вечерняя звезда: бычья большая → маленькая → медвежья большая.
    """
    return (
        _is_bullish(c1) and _body(c1) > _body(c2)
        and _body(c2) < _body(c1) * 0.4
        and _is_bearish(c3)
        and c3["close"] < (c1["open"] + c1["close"]) / 2
    )


def is_three_white_soldiers(c1: pd.Series, c2: pd.Series, c3: pd.Series) -> bool:
    """Три белых солдата: три последовательно растущих бычьих свечи."""
    return (
        _is_bullish(c1) and _is_bullish(c2) and _is_bullish(c3)
        and c2["open"] > c1["open"] and c2["close"] > c1["close"]
        and c3["open"] > c2["open"] and c3["close"] > c2["close"]
        and _upper_shadow(c1) < _body(c1) * 0.3
        and _upper_shadow(c2) < _body(c2) * 0.3
    )


def is_three_black_crows(c1: pd.Series, c2: pd.Series, c3: pd.Series) -> bool:
    """Три чёрных вороны: три последовательно падающих медвежьих свечи."""
    return (
        _is_bearish(c1) and _is_bearish(c2) and _is_bearish(c3)
        and c2["open"] < c1["open"] and c2["close"] < c1["close"]
        and c3["open"] < c2["open"] and c3["close"] < c2["close"]
        and _lower_shadow(c1) < _body(c1) * 0.3
        and _lower_shadow(c2) < _body(c2) * 0.3
    )


# ── Главная функция ────────────────────────────────────────────────────────────

def detect(df: pd.DataFrame, lookback: int = 3) -> list[dict]:
    """
    Сканирует последние `lookback` свечей и возвращает найденные паттерны.

    Returns:
        [{"pattern": str, "direction": "bullish"|"bearish"|"neutral",
          "strength": "strong"|"medium"|"weak", "candle_index": int}, ...]
    """
    found: list[dict] = []
    n = len(df)
    if n < 3:
        return found

    for i in range(max(0, n - lookback), n):
        row  = df.iloc[i]
        prev = df.iloc[i - 1] if i > 0 else row
        pp   = df.iloc[i - 2] if i > 1 else prev

        # Одиночные
        if is_doji(row):
            found.append({"pattern": "Doji", "direction": "neutral",
                          "strength": "weak", "candle_index": i})
        if is_hammer(row):
            found.append({"pattern": "Hammer", "direction": "bullish",
                          "strength": "medium", "candle_index": i})
        if is_shooting_star(row):
            found.append({"pattern": "Shooting Star", "direction": "bearish",
                          "strength": "medium", "candle_index": i})
        if is_marubozu_bull(row):
            found.append({"pattern": "Bullish Marubozu", "direction": "bullish",
                          "strength": "strong", "candle_index": i})
        if is_marubozu_bear(row):
            found.append({"pattern": "Bearish Marubozu", "direction": "bearish",
                          "strength": "strong", "candle_index": i})

        # Двухсвечные
        if i > 0:
            if is_bullish_engulfing(prev, row):
                found.append({"pattern": "Bullish Engulfing", "direction": "bullish",
                              "strength": "strong", "candle_index": i})
            if is_bearish_engulfing(prev, row):
                found.append({"pattern": "Bearish Engulfing", "direction": "bearish",
                              "strength": "strong", "candle_index": i})
            if is_tweezer_bottom(prev, row):
                found.append({"pattern": "Tweezer Bottom", "direction": "bullish",
                              "strength": "medium", "candle_index": i})
            if is_tweezer_top(prev, row):
                found.append({"pattern": "Tweezer Top", "direction": "bearish",
                              "strength": "medium", "candle_index": i})

        # Трёхсвечные
        if i > 1:
            if is_morning_star(pp, prev, row):
                found.append({"pattern": "Morning Star", "direction": "bullish",
                              "strength": "strong", "candle_index": i})
            if is_evening_star(pp, prev, row):
                found.append({"pattern": "Evening Star", "direction": "bearish",
                              "strength": "strong", "candle_index": i})
            if is_three_white_soldiers(pp, prev, row):
                found.append({"pattern": "Three White Soldiers", "direction": "bullish",
                              "strength": "strong", "candle_index": i})
            if is_three_black_crows(pp, prev, row):
                found.append({"pattern": "Three Black Crows", "direction": "bearish",
                              "strength": "strong", "candle_index": i})

    return found
