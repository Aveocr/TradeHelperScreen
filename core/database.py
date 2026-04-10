from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator

from core.config import config
from core.logger import get_logger

logger = get_logger(__name__)

DB_PATH = Path(config.DB_PATH)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


SCHEMA = """
-- Торговые рекомендации, выданные агентом
CREATE TABLE IF NOT EXISTS recommendations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    exchange    TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    market_type TEXT    NOT NULL,          -- spot / futures
    direction   TEXT    NOT NULL,          -- long / short
    entry_price REAL    NOT NULL,
    sl_price    REAL    NOT NULL,
    tp1_price   REAL    NOT NULL,
    tp2_price   REAL,
    tp3_price   REAL,
    entry_size  REAL    NOT NULL,
    max_loss    REAL    NOT NULL,
    rr_ratio    REAL    NOT NULL,
    reasoning   TEXT,                      -- объяснение от Claude
    status      TEXT    NOT NULL DEFAULT 'open'  -- open / closed / cancelled
);

-- Дневная статистика просадки
CREATE TABLE IF NOT EXISTS daily_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date      TEXT    NOT NULL UNIQUE,   -- YYYY-MM-DD
    realized_pnl    REAL    NOT NULL DEFAULT 0.0,
    trades_count    INTEGER NOT NULL DEFAULT 0,
    losses_count    INTEGER NOT NULL DEFAULT 0,
    session_blocked INTEGER NOT NULL DEFAULT 0  -- 1 если лимит просадки достигнут
);

-- Лог пре-сессионных проверок
CREATE TABLE IF NOT EXISTS session_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    emotional_score INTEGER NOT NULL,          -- 1-10
    user_notes      TEXT,
    agent_advice    TEXT,
    session_allowed INTEGER NOT NULL DEFAULT 1 -- 0 если агент не рекомендует торговать
);
"""


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Создаёт таблицы, если они ещё не существуют."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
    logger.info(f"База данных инициализирована: {DB_PATH}")


# ---------------------------------------------------------------------------
# Daily stats helpers
# ---------------------------------------------------------------------------

def get_today_stats() -> dict:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM daily_stats WHERE trade_date = ?", (today,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO daily_stats (trade_date) VALUES (?)", (today,)
            )
            return {
                "trade_date": today,
                "realized_pnl": 0.0,
                "trades_count": 0,
                "losses_count": 0,
                "session_blocked": 0,
            }
        return dict(row)


def update_daily_pnl(pnl_delta: float) -> dict:
    """
    Обновляет дневной P&L. Если достигнут лимит просадки — блокирует сессию.
    Возвращает обновлённую запись.
    """
    today = date.today().isoformat()
    stats = get_today_stats()

    new_pnl = round(stats["realized_pnl"] + pnl_delta, 4)
    new_trades = stats["trades_count"] + 1
    new_losses = stats["losses_count"] + (1 if pnl_delta < 0 else 0)
    blocked = 1 if new_pnl <= -config.DAILY_DRAWDOWN_LIMIT else 0

    with get_conn() as conn:
        conn.execute(
            """
            UPDATE daily_stats
               SET realized_pnl    = ?,
                   trades_count    = ?,
                   losses_count    = ?,
                   session_blocked = ?
             WHERE trade_date = ?
            """,
            (new_pnl, new_trades, new_losses, blocked, today),
        )

    updated = {
        "trade_date": today,
        "realized_pnl": new_pnl,
        "trades_count": new_trades,
        "losses_count": new_losses,
        "session_blocked": blocked,
    }

    if blocked:
        logger.warning(
            f"[red]ДНЕВНОЙ ЛИМИТ ПРОСАДКИ ДОСТИГНУТ[/red] | "
            f"P&L: {new_pnl:.2f}$ / -{config.DAILY_DRAWDOWN_LIMIT}$"
        )

    return updated


def is_session_blocked() -> bool:
    return bool(get_today_stats()["session_blocked"])
