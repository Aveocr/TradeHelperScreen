"""
Калькулятор риск-менеджмента.
Рассчитывает размер позиции, SL и TP с учётом правил:
  - Вход: ENTRY_SIZE$
  - Макс. убыток: MAX_LOSS_PER_TRADE$ (= 10% от входа)
  - Мин. R:R = MIN_RR_RATIO : 1
  - TP1 = +3R, TP2 = +5R, TP3 = +8R
"""

from __future__ import annotations

from dataclasses import dataclass
from core.config import config


@dataclass
class TradeSetup:
    """Полный расчёт параметров сделки."""
    direction:   str    # "long" | "short"
    entry_price: float
    sl_price:    float
    tp1_price:   float
    tp2_price:   float
    tp3_price:   float
    entry_size:  float  # $ входа
    qty:         float  # количество монет
    max_loss:    float  # $ убытка при SL
    sl_pct:      float  # % до SL
    tp1_pct:     float  # % до TP1
    rr_ratio:    float  # реальный R:R до TP1
    is_valid:    bool
    warning:     str


def calculate(
    direction: str,
    entry_price: float,
    sl_price: float | None = None,
    atr: float | None = None,
    nearest_support: float | None = None,
    nearest_resistance: float | None = None,
) -> TradeSetup:
    """
    Рассчитывает все параметры сделки.

    Если sl_price не задан — определяет SL автоматически:
      - По ATR × 1.5 (если передан)
      - По ближайшему уровню (если передан)
      - По фиксированному 10% от входа (запасной вариант)

    Args:
        direction:           "long" или "short"
        entry_price:         цена входа
        sl_price:            цена стоп-лосса (опционально)
        atr:                 значение ATR (опционально)
        nearest_support:     ближайший уровень поддержки (для long SL)
        nearest_resistance:  ближайший уровень сопротивления (для short SL)
    """
    entry  = config.ENTRY_SIZE
    max_loss = config.MAX_LOSS_PER_TRADE
    rr_min = config.MIN_RR_RATIO

    # ── Определяем SL ─────────────────────────────────────────────────────────
    if sl_price is None:
        sl_price = _auto_sl(
            direction, entry_price, max_loss, entry,
            atr, nearest_support, nearest_resistance,
        )

    # ── Расстояния ────────────────────────────────────────────────────────────
    if direction == "long":
        sl_dist  = entry_price - sl_price
        if sl_dist <= 0:
            return _invalid(direction, entry_price, "SL должен быть ниже цены входа для long")
        tp1_price = entry_price + sl_dist * 3
        tp2_price = entry_price + sl_dist * 5
        tp3_price = entry_price + sl_dist * 8
    else:  # short
        sl_dist  = sl_price - entry_price
        if sl_dist <= 0:
            return _invalid(direction, entry_price, "SL должен быть выше цены входа для short")
        tp1_price = entry_price - sl_dist * 3
        tp2_price = entry_price - sl_dist * 5
        tp3_price = entry_price - sl_dist * 8

    # ── Размер позиции ─────────────────────────────────────────────────────────
    # Сколько монет купить, чтобы при достижении SL потерять max_loss$
    qty = max_loss / sl_dist if sl_dist > 0 else 0

    # Реальный размер входа в $
    real_entry_size = qty * entry_price

    # Если реальный вход превышает ENTRY_SIZE — ограничиваем и пересчитываем
    if real_entry_size > entry:
        qty = entry / entry_price
        real_entry_size = entry
        actual_loss = qty * sl_dist
    else:
        actual_loss = max_loss

    # ── Проценты ──────────────────────────────────────────────────────────────
    sl_pct  = sl_dist / entry_price * 100
    tp1_pct = sl_dist * 3 / entry_price * 100
    rr      = sl_dist * 3 / sl_dist  # = 3 всегда

    # ── Валидация ──────────────────────────────────────────────────────────────
    warning = ""
    if sl_pct > 15:
        warning = f"SL очень далеко ({sl_pct:.1f}%) — риск потери больше ${actual_loss:.2f}"
    elif sl_pct < 0.3:
        warning = f"SL очень близко ({sl_pct:.2f}%) — высокий риск случайного срабатывания"

    return TradeSetup(
        direction   = direction,
        entry_price = round(entry_price, 8),
        sl_price    = round(sl_price, 8),
        tp1_price   = round(tp1_price, 8),
        tp2_price   = round(tp2_price, 8),
        tp3_price   = round(tp3_price, 8),
        entry_size  = round(real_entry_size, 2),
        qty         = round(qty, 6),
        max_loss    = round(actual_loss, 4),
        sl_pct      = round(sl_pct, 2),
        tp1_pct     = round(tp1_pct, 2),
        rr_ratio    = rr_min,
        is_valid    = True,
        warning     = warning,
    )


def to_dict(setup: TradeSetup) -> dict:
    """Конвертирует TradeSetup в словарь для API/Claude."""
    return {
        "direction":   setup.direction,
        "entry_price": setup.entry_price,
        "sl_price":    setup.sl_price,
        "tp1_price":   setup.tp1_price,
        "tp2_price":   setup.tp2_price,
        "tp3_price":   setup.tp3_price,
        "entry_size":  setup.entry_size,
        "qty":         setup.qty,
        "max_loss":    setup.max_loss,
        "sl_pct":      setup.sl_pct,
        "tp1_pct":     setup.tp1_pct,
        "rr_ratio":    setup.rr_ratio,
        "is_valid":    setup.is_valid,
        "warning":     setup.warning,
    }


# ── Вспомогательные ───────────────────────────────────────────────────────────

def _auto_sl(
    direction: str,
    entry_price: float,
    max_loss: float,
    entry_size: float,
    atr: float | None,
    support: float | None,
    resistance: float | None,
) -> float:
    """Автоматически определяет SL по приоритету."""

    # Приоритет 1: ближайший уровень (с буфером 0.2%)
    if direction == "long" and support and support < entry_price:
        return support * 0.998
    if direction == "short" and resistance and resistance > entry_price:
        return resistance * 1.002

    # Приоритет 2: ATR × 1.5
    if atr and atr > 0:
        if direction == "long":
            return entry_price - atr * 1.5
        else:
            return entry_price + atr * 1.5

    # Приоритет 3: фиксированный процент (max_loss / entry_size)
    sl_pct = max_loss / entry_size
    if direction == "long":
        return entry_price * (1 - sl_pct)
    else:
        return entry_price * (1 + sl_pct)


def _invalid(direction: str, entry_price: float, reason: str) -> TradeSetup:
    return TradeSetup(
        direction   = direction,
        entry_price = entry_price,
        sl_price    = 0,
        tp1_price   = 0,
        tp2_price   = 0,
        tp3_price   = 0,
        entry_size  = 0,
        qty         = 0,
        max_loss    = 0,
        sl_pct      = 0,
        tp1_pct     = 0,
        rr_ratio    = 0,
        is_valid    = False,
        warning     = reason,
    )
