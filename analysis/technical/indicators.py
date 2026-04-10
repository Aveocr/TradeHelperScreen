"""
Технические индикаторы.
Принимает pandas DataFrame с колонками: open, high, low, close, volume.
Возвращает DataFrame с добавленными колонками индикаторов.
"""

from __future__ import annotations

import pandas as pd
import numpy as np


def add_ema(df: pd.DataFrame, periods: list[int] = [9, 21, 50, 200]) -> pd.DataFrame:
    """Exponential Moving Average."""
    for p in periods:
        df[f"ema_{p}"] = df["close"].ewm(span=p, adjust=False).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Relative Strength Index."""
    delta = df["close"].diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def add_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD + Signal + Histogram."""
    ema_fast   = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow   = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"]        = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]
    return df


def add_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Bands: middle, upper, lower, bandwidth, %B."""
    mid = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    df["bb_mid"]   = mid
    df["bb_upper"] = mid + std_dev * std
    df["bb_lower"] = mid - std_dev * std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / mid
    df["bb_pct"]   = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average True Range — мера волатильности."""
    high  = df["high"]
    low   = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(com=period - 1, min_periods=period).mean()
    df["atr_pct"] = df["atr"] / df["close"] * 100   # ATR в % от цены
    return df


def add_volume_analysis(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Объёмный анализ: средний объём, отклонение, delta."""
    df["vol_ma"]    = df["volume"].rolling(period).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma"]          # >1 = объём выше среднего
    # Примерный дельта-объём (покупки vs продажи через свечу)
    body     = df["close"] - df["open"]
    df["vol_delta"] = df["volume"] * body.apply(lambda x: 1 if x > 0 else -1)
    df["vol_delta_ma"] = df["vol_delta"].rolling(period).mean()
    return df


def add_stochastic(
    df: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
) -> pd.DataFrame:
    """Stochastic Oscillator (%K и %D)."""
    low_min  = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    df["stoch_k"] = (df["close"] - low_min) / (high_max - low_min) * 100
    df["stoch_d"] = df["stoch_k"].rolling(d_period).mean()
    return df


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    VWAP (Volume Weighted Average Price).
    Считается накопительно по всем свечам DataFrame — для внутридневного использования
    передавай только свечи за текущий день.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol  = df["volume"].cumsum()
    cum_tp_vol = (typical * df["volume"]).cumsum()
    df["vwap"] = cum_tp_vol / cum_vol
    return df


# ── Главная функция ───────────────────────────────────────────────────────────

def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Добавляет все индикаторы в один проход.
    Возвращает DataFrame с полным набором колонок.
    """
    df = df.copy()
    df = add_ema(df, [9, 21, 50, 200])
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger_bands(df)
    df = add_atr(df)
    df = add_volume_analysis(df)
    df = add_stochastic(df)
    df = add_vwap(df)
    return df


def get_last(df: pd.DataFrame) -> dict:
    """
    Возвращает последние значения всех индикаторов в виде словаря.
    Удобно для передачи в Claude или отображения в UI.
    """
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    def v(col: str) -> float | None:
        val = last.get(col)
        return round(float(val), 6) if pd.notna(val) else None

    return {
        "close":        v("close"),
        "volume":       v("volume"),
        # EMA
        "ema_9":        v("ema_9"),
        "ema_21":       v("ema_21"),
        "ema_50":       v("ema_50"),
        "ema_200":      v("ema_200"),
        # RSI
        "rsi":          v("rsi"),
        "rsi_prev":     round(float(prev.get("rsi")), 2) if pd.notna(prev.get("rsi")) else None,
        # MACD
        "macd":         v("macd"),
        "macd_signal":  v("macd_signal"),
        "macd_hist":    v("macd_hist"),
        "macd_cross":   _macd_cross(df),
        # Bollinger
        "bb_upper":     v("bb_upper"),
        "bb_mid":       v("bb_mid"),
        "bb_lower":     v("bb_lower"),
        "bb_pct":       v("bb_pct"),
        "bb_width":     v("bb_width"),
        # ATR
        "atr":          v("atr"),
        "atr_pct":      v("atr_pct"),
        # Volume
        "vol_ratio":    v("vol_ratio"),
        "vol_delta_ma": v("vol_delta_ma"),
        # Stochastic
        "stoch_k":      v("stoch_k"),
        "stoch_d":      v("stoch_d"),
        # VWAP
        "vwap":         v("vwap"),
        # EMA trend
        "ema_trend":    _ema_trend(last),
    }


def _macd_cross(df: pd.DataFrame) -> str:
    """Определяет последний пересечение MACD."""
    if len(df) < 2:
        return "none"
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    if (pd.notna(curr.get("macd")) and pd.notna(curr.get("macd_signal"))
            and pd.notna(prev.get("macd")) and pd.notna(prev.get("macd_signal"))):
        if prev["macd"] < prev["macd_signal"] and curr["macd"] > curr["macd_signal"]:
            return "bullish"
        if prev["macd"] > prev["macd_signal"] and curr["macd"] < curr["macd_signal"]:
            return "bearish"
    return "none"


def _ema_trend(row: pd.Series) -> str:
    """Определяет тренд по расположению EMA."""
    e9  = row.get("ema_9")
    e21 = row.get("ema_21")
    e50 = row.get("ema_50")
    if any(pd.isna(x) for x in [e9, e21, e50]):
        return "unknown"
    if e9 > e21 > e50:
        return "uptrend"
    if e9 < e21 < e50:
        return "downtrend"
    return "sideways"
