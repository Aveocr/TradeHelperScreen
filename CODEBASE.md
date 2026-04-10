# AI Trading Assistant — Полная документация кодовой базы

> **Назначение документа:** Описание архитектуры, всех модулей, классов, методов и API-эндпоинтов для отладки.
> **Язык реализации:** Python 3.11+  
> **Стек:** FastAPI · ccxt · pandas · anthropic · SQLite · Jinja2 · PRAW  
> **Точка входа:** `python main.py web` (HTTP 127.0.0.1:8000) или `python main.py cli`

---

## Структура проекта

```
AI-trade-assistante/
├── main.py                        # точка входа (web / cli)
├── .env                           # API-ключи и конфиг (не в git)
├── requirements.txt
│
├── core/
│   ├── config.py                  # объект Config с параметрами риска
│   ├── database.py                # SQLite: recommendations, daily_stats, session_logs
│   └── logger.py                  # Rich + файловый лог
│
├── exchanges/
│   ├── base.py                    # абстрактный BaseExchange
│   └── gate.py                    # GateExchange (ccxt async) — spot + futures
│
├── data/
│   ├── market_data.py             # MarketDataService: OHLCV DataFrame + скринер
│   └── orderbook.py               # OrderBookAnalyzer: ликвидность, кластеры, давление
│
├── analysis/
│   ├── technical/
│   │   ├── indicators.py          # EMA, RSI, MACD, BB, ATR, Stoch, VWAP, Volume
│   │   ├── patterns.py            # свечные паттерны (Doji, Hammer, Engulfing, ...)
│   │   ├── levels.py              # пивот-уровни, кластеры поддержки/сопротивления
│   │   └── signals.py             # агрегирующий генератор сигнала (-100..+100)
│   └── sentiment/
│       ├── reddit.py              # PRAW парсер Reddit, ключевые слова bull/bear
│       └── scorer.py              # агрегатор: Reddit ИЛИ TA-fallback
│
├── risk/
│   └── calculator.py              # TradeSetup: SL, TP1/2/3, qty, R:R
│
├── agent/
│   ├── prompts.py                 # SYSTEM_TRADING, SYSTEM_SESSION (шаблоны Claude)
│   ├── claude_agent.py            # TradingAgent: analyze(), analyze_stream(), session_check()
│   └── recommender.py             # build_recommendation(): полный pipeline
│
├── web/
│   ├── app.py                     # FastAPI app, lifespan, роутеры
│   ├── routers/
│   │   ├── dashboard.py           # GET / /screener /analysis
│   │   ├── market.py              # /api/market/ticker|orderbook|ta|screener|stats
│   │   ├── session.py             # GET/POST /session/
│   │   ├── agent.py               # GET /agent/recommend|stream|history POST /agent/session
│   │   ├── positions.py           # /positions/ + /positions/api/*
│   │   └── settings.py            # /settings/ + /settings/api/*
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── screener.html
│   │   ├── analysis.html
│   │   ├── recommend.html
│   │   ├── session.html
│   │   ├── positions.html
│   │   └── settings.html
│   └── static/
│       ├── css/style.css          # dark theme (--bg:#0d0f14)
│       └── js/main.js             # fmtPrice(), fmtVol(), checkConnection()
│
├── ui/
│   └── cli.py                     # Rich CLI (альтернатива web)
│
└── data/
    └── trading.db                 # SQLite (создаётся автоматически)
```

---

## .env — переменные окружения

| Переменная | Обязательная | Описание |
|---|---|---|
| `GATE_API_KEY` | ✅ | API ключ Gate.io |
| `GATE_API_SECRET` | ✅ | API секрет Gate.io |
| `ANTHROPIC_API_KEY` | ✅ | Ключ Claude API |
| `REDDIT_CLIENT_ID` | ❌ | Reddit app client_id (без него Reddit недоступен — fallback на TA) |
| `REDDIT_CLIENT_SECRET` | ❌ | Reddit app client_secret |
| `REDDIT_USER_AGENT` | ❌ | User-agent для PRAW (default: TradingBot/1.0) |
| `ENTRY_SIZE` | ❌ | Размер входа $ (default: 10.0) |
| `MAX_LOSS_PER_TRADE` | ❌ | Макс. убыток на сделку $ (default: 1.0) |
| `DAILY_DRAWDOWN_LIMIT` | ❌ | Лимит просадки за день $ (default: 6.0) |
| `MIN_RR_RATIO` | ❌ | Минимальный R:R (default: 3.0) |

---

## core/config.py

### Класс `Config`

Синглтон `config = Config()`, доступный через `from core.config import config`.

```python
config.GATE_API_KEY          # str
config.GATE_API_SECRET       # str
config.ANTHROPIC_API_KEY     # str
config.REDDIT_CLIENT_ID      # str
config.REDDIT_CLIENT_SECRET  # str
config.REDDIT_USER_AGENT     # str
config.ENTRY_SIZE            # float — размер входа в USDT
config.MAX_LOSS_PER_TRADE    # float — макс. убыток за сделку в USDT
config.DAILY_DRAWDOWN_LIMIT  # float — дневной лимит просадки в USDT
config.MIN_RR_RATIO          # float — минимальный R:R
config.DB_PATH               # str — путь к SQLite (data/trading.db)
config.CLAUDE_MODEL          # str — "claude-sonnet-4-6"
```

**Метод `validate()`** — выбрасывает `EnvironmentError` если `GATE_API_KEY` или `ANTHROPIC_API_KEY` не заданы.

> **Важно для отладки:** параметры риска (`ENTRY_SIZE`, `MAX_LOSS_PER_TRADE`, `DAILY_DRAWDOWN_LIMIT`, `MIN_RR_RATIO`) могут быть изменены в рантайме через `/settings/api/update`. Роутер settings.py напрямую переписывает атрибуты объекта `config`.

---

## core/database.py

SQLite (`data/trading.db`). Схема создаётся при старте через `init_db()`.

### Таблицы

#### `recommendations`
| Колонка | Тип | Описание |
|---|---|---|
| `id` | INTEGER PK | |
| `created_at` | TEXT | ISO datetime |
| `exchange` | TEXT | "gate" |
| `symbol` | TEXT | "BTC/USDT" |
| `market_type` | TEXT | "spot" / "futures" |
| `direction` | TEXT | "long" / "short" |
| `entry_price` | REAL | |
| `sl_price` | REAL | |
| `tp1_price` | REAL | |
| `tp2_price` | REAL | |
| `tp3_price` | REAL | |
| `entry_size` | REAL | |
| `max_loss` | REAL | |
| `rr_ratio` | REAL | |
| `reasoning` | TEXT | текст от Claude (до 2000 символов) |
| `status` | TEXT | "open" / "closed" / "cancelled" |

#### `daily_stats`
| Колонка | Тип | Описание |
|---|---|---|
| `trade_date` | TEXT UNIQUE | "YYYY-MM-DD" |
| `realized_pnl` | REAL | суммарный P&L за день |
| `trades_count` | INTEGER | количество сделок |
| `losses_count` | INTEGER | количество убыточных |
| `session_blocked` | INTEGER | 1 если лимит достигнут |

#### `session_logs`
| Колонка | Тип | Описание |
|---|---|---|
| `emotional_score` | INTEGER | 1–10 |
| `user_notes` | TEXT | |
| `agent_advice` | TEXT | ответ Claude |
| `session_allowed` | INTEGER | 0 = торговать нельзя |

### Функции

```python
get_conn() -> ContextManager[sqlite3.Connection]
# contextmanager: открывает соединение, commit при выходе, rollback при ошибке

init_db() -> None
# Создаёт все таблицы (идемпотентно, IF NOT EXISTS)

get_today_stats() -> dict
# Возвращает запись daily_stats за сегодня.
# Если записи нет — создаёт новую и возвращает дефолтные нули.
# Возвращает: {trade_date, realized_pnl, trades_count, losses_count, session_blocked}

update_daily_pnl(pnl_delta: float) -> dict
# Прибавляет pnl_delta к realized_pnl.
# Если новый pnl <= -DAILY_DRAWDOWN_LIMIT → session_blocked = 1.
# Логирует предупреждение при блокировке.

is_session_blocked() -> bool
# Обёртка над get_today_stats()["session_blocked"]
```

---

## exchanges/gate.py

### Класс `GateExchange(BaseExchange)`

Два ccxt-клиента внутри: `_spot` (defaultType="spot") и `_futures` (defaultType="future").
Все методы — **async**.

```python
exchange = GateExchange()
# Инициализирует ccxt.gateio с API ключами из config
```

### Методы получения данных

```python
async get_ohlcv(symbol, timeframe="5m", limit=200, market_type="spot") -> list[dict]
# Возвращает: [{"timestamp": ms, "open", "high", "low", "close", "volume"}, ...]
# Raises: ValueError если symbol не найден, ValueError если timeframe не поддерживается
# Поддерживаемые timeframes: 1m 5m 15m 30m 1h 4h 8h 1d 1w

async get_ticker(symbol, market_type="spot") -> dict
# Возвращает: {"symbol", "last", "bid", "ask", "volume_24h", "quote_vol_24h",
#              "change_24h_pct", "high_24h", "low_24h"}

async get_orderbook(symbol, depth=20, market_type="spot") -> dict
# Возвращает: {"bids": [[price, size], ...], "asks": [[price, size], ...],
#              "best_bid", "best_ask", "spread", "spread_pct"}

async get_markets(market_type=None) -> list[dict]
# market_type: "spot" | "futures" | None (оба)
# Возвращает: [{"symbol", "base", "quote", "market_type", "min_amount", "precision"}, ...]
```

### Методы торговли

```python
async get_positions(market_type="futures") -> list[dict]
# Для futures: fetch_positions() → фильтрует позиции с contracts > 0
# Для spot: fetch_balance() → ненулевые балансы с рыночной ценой (игнорирует < $1)
# Возвращает: [{"symbol", "side", "contracts", "notional", "entry_price",
#               "mark_price", "pnl", "pnl_pct", "liq_price", "leverage", "market_type"}, ...]
# Для спота: entry_price=0.0, pnl=0.0 (Gate.io не хранит историческую цену входа на споте)

async place_order(symbol, side, amount, price=None, order_type="limit", market_type="spot") -> dict
# side: "buy" | "sell"
# order_type: "limit" | "market"
# Для limit — price обязателен, иначе ValueError
# Возвращает: {"id", "symbol", "side", "type", "amount", "price", "status"}

async close_position_market(symbol, side, amount, market_type="futures") -> dict
# Закрывает позицию по рынку:
#   long → create_market_order(side="sell")
#   short → create_market_order(side="buy")

async get_open_orders(symbol=None, market_type="spot") -> list[dict]
# Возвращает: [{"id", "symbol", "side", "type", "amount", "price",
#               "filled", "remaining", "status", "timestamp"}, ...]

async cancel_order(order_id, symbol, market_type="spot") -> dict
# Возвращает: {"id", "status"}

async close() -> None
# Закрывает оба ccxt-клиента (_spot и _futures)
```

> **Потенциальные проблемы:**
> - `get_positions("spot")` делает дополнительный запрос `fetch_ticker` для каждой валюты — может быть медленным при большом количестве монет в балансе.
> - Для фьючерсов Gate.io возвращает `contracts` в `p.get("contracts")`, но иногда это поле `contractSize`. Код проверяет оба варианта.

---

## data/market_data.py

### Класс `MarketDataService`

```python
svc = MarketDataService(exchange)
```

```python
async get_ohlcv_df(symbol, timeframe="5m", limit=200, market_type="spot") -> pd.DataFrame
# Колонки: timestamp (DatetimeIndex, UTC), open, high, low, close, volume (все float)
# Индекс — timestamp, отсортирован по возрастанию

async get_ticker(symbol, market_type="spot") -> dict
# Проксирует exchange.get_ticker()

async get_multi_timeframe(symbol, timeframes: list[str], limit=200, market_type="spot") -> dict[str, pd.DataFrame]
# Параллельные запросы через asyncio.gather
# Возвращает {"5m": df, "1h": df, ...}, ошибки логирует и пропускает

async scan_volume_leaders(quote_currency="USDT", market_type="spot", top_n=30, min_quote_volume=1_000_000) -> list[dict]
# 1. Загружает все рынки → фильтрует по quote == USDT
# 2. Параллельно запрашивает тикеры (safe_ticker — молчит при ошибках)
# 3. Фильтрует по min_quote_volume, сортирует по объёму desc
# 4. Возвращает топ top_n тикеров
# Возвращает те же dict, что get_ticker()
```

---

## data/orderbook.py

### Класс `OrderBookAnalyzer`

```python
analyzer = OrderBookAnalyzer(exchange)
```

```python
async analyze(symbol, depth=20, market_type="spot") -> dict
# Полный анализ стакана.
# Возвращает:
# {
#   "symbol", "market_type",
#   "best_bid", "best_ask", "spread", "spread_pct",
#   "is_liquid": bool,           # spread_pct <= 0.3%
#   "bid_volume", "ask_volume",
#   "pressure": "buy"|"sell"|"neutral",
#   "pressure_ratio": float,     # bid_vol / ask_vol
#   "support_levels":    [{"price", "size", "volume_pct"}, ...],  # топ-3 bids
#   "resistance_levels": [{"price", "size", "volume_pct"}, ...],  # топ-3 asks
# }
# pressure_ratio > 1.15 → "buy", < 0.87 → "sell", иначе "neutral"

liquidity_verdict(analysis: dict) -> str
# Текстовый вердикт: "Ликвидность OK | ..." или "Инструмент НЕЛИКВИДЕН..."
```

---

## analysis/technical/indicators.py

Все функции принимают `pd.DataFrame` с колонками `open, high, low, close, volume` и возвращают новый DataFrame с добавленными колонками.

```python
add_ema(df, periods=[9, 21, 50, 200]) -> df
# Добавляет: ema_9, ema_21, ema_50, ema_200

add_rsi(df, period=14) -> df
# Добавляет: rsi

add_macd(df, fast=12, slow=26, signal=9) -> df
# Добавляет: macd, macd_signal, macd_hist

add_bollinger_bands(df, period=20, std=2.0) -> df
# Добавляет: bb_upper, bb_middle, bb_lower, bb_pct (= (close-lower)/(upper-lower))

add_atr(df, period=14) -> df
# Добавляет: atr, atr_pct (= atr/close*100)

add_volume_analysis(df, period=20) -> df
# Добавляет: vol_ma (скользящее среднее объёма), vol_ratio (volume/vol_ma)

add_stochastic(df, k_period=14, d_period=3) -> df
# Добавляет: stoch_k, stoch_d

add_vwap(df) -> df
# Добавляет: vwap (объёмно-взвешенная средняя цена за весь DataFrame)

compute_all(df) -> df
# Вызывает все функции выше в правильном порядке

get_last(df) -> dict
# Возвращает последнюю строку всех индикаторов + вычисляемые поля:
# {
#   "close", "ema_9", "ema_21", "ema_50", "ema_200",
#   "rsi", "macd", "macd_signal", "macd_hist",
#   "bb_upper", "bb_lower", "bb_pct",
#   "atr", "atr_pct",
#   "vol_ratio", "stoch_k", "stoch_d", "vwap",
#   "ema_trend": "uptrend"|"downtrend"|"mixed",  # 9>21>50 или 9<21<50
#   "macd_cross": "bullish"|"bearish"|None,       # пересечение за последние 3 свечи
# }
```

---

## analysis/technical/patterns.py

```python
detect(df: pd.DataFrame, lookback=5) -> list[dict]
# Сканирует последние lookback свечей.
# Возвращает:
# [{"pattern": str, "direction": "bullish"|"bearish"|"neutral",
#   "strength": "strong"|"medium"|"weak", "candle_index": int}, ...]

# Поддерживаемые паттерны:
# Одиночные:
#   Doji             → neutral, weak
#   Hammer           → bullish, medium (нижняя тень ≥ 2×тело, верхняя ≤ 10%)
#   Shooting Star    → bearish, medium
#   Marubozu Bull    → bullish, medium (тело > 90% диапазона, бычья свеча)
#   Marubozu Bear    → bearish, medium
#
# Двойные (требуют предыдущую свечу):
#   Bullish Engulfing → bullish, strong (тело поглощает предыдущее)
#   Bearish Engulfing → bearish, strong
#   Tweezer Bottom   → bullish, weak  (одинаковые минимумы)
#   Tweezer Top      → bearish, weak
#
# Тройные (требуют 2 предыдущие свечи):
#   Morning Star     → bullish, strong
#   Evening Star     → bearish, strong
#   Three White Soldiers → bullish, strong
#   Three Black Crows    → bearish, strong
```

---

## analysis/technical/levels.py

```python
find_pivot_levels(df: pd.DataFrame, left=5, right=5, merge_pct=0.5) -> dict
# Ищет локальные максимумы (resistance) и минимумы (support) через пивот-метод.
# Кластеризует близкие уровни (в пределах merge_pct% друг от друга).
# Возвращает:
# {
#   "support":    [{"price": float, "touches": int, "strength": "strong"|"medium"|"weak"}, ...],
#   "resistance": [{"price": float, "touches": int, "strength": "strong"|"medium"|"weak"}, ...],
# }
# strength: touches >= 3 → "strong", >= 2 → "medium", иначе "weak"

nearest_levels(levels: dict, current_price: float, n=3) -> dict
# Фильтрует уровни: поддержки ниже цены, сопротивления выше.
# Возвращает n ближайших с каждой стороны.
# Возвращает:
# {
#   "nearest_support":    [{"price", "touches", "strength", "dist_pct"}, ...],
#   "nearest_resistance": [{"price", "touches", "strength", "dist_pct"}, ...],
# }

find_range(df: pd.DataFrame, period=20) -> dict
# Диапазон последних period свечей.
# Возвращает: {"high", "low", "mid", "width_pct"}
```

---

## analysis/technical/signals.py

```python
generate(df: pd.DataFrame, timeframe="5m") -> dict
# Главная функция ТА — запускает полный пайплайн.
# Минимум 50 свечей, иначе возвращает пустой сигнал.
#
# Алгоритм:
#   1. compute_all(df) + get_last() → ind
#   2. detect(df, lookback=5) → паттерны
#   3. find_pivot_levels() + nearest_levels() → уровни
#   4. _score() → score (-100..+100), reasons
#   5. direction: score >= 25 → "long", <= -25 → "short", иначе "neutral"
#   6. confidence: |score| >= 50 → "high", иначе "medium" (или "low" при neutral)
#
# Возвращает:
# {
#   "direction": "long"|"short"|"neutral",
#   "score": int,            # -100..+100
#   "confidence": "high"|"medium"|"low",
#   "timeframe": str,
#   "indicators": dict,      # get_last() результат
#   "patterns": list[dict],
#   "levels": dict,          # все уровни
#   "nearest": dict,         # ближайшие уровни
#   "range": dict,
#   "reasons": list[str],    # текстовые объяснения скора
# }
```

### Таблица скоринга

| Сигнал | Очки bull | Очки bear |
|---|---|---|
| EMA тренд (9>21>50 или наоборот) | +20 | −20 |
| Цена vs EMA 50 | +10 | −10 |
| RSI < 30 | +20 | — |
| RSI > 70 | — | −20 |
| RSI 30–45 / 55–70 | +8 | −8 |
| MACD cross bullish/bearish | +15 | −15 |
| MACD hist > 0 / < 0 | +5 | −5 |
| BB %B < 0.1 (у нижней полосы) | +12 | — |
| BB %B > 0.9 (у верхней полосы) | — | −12 |
| Stochastic < 20 / > 80 | +10 | −10 |
| Цена vs VWAP | +5 | −5 |
| Паттерн strong | ±15 | — |
| Паттерн medium | ±8 | — |
| Паттерн weak | ±3 | — |
| Близость к уровню (< 0.5%) | +8 sup / −8 res | — |

---

## risk/calculator.py

### Dataclass `TradeSetup`

```python
@dataclass
class TradeSetup:
    direction:   str    # "long" | "short"
    entry_price: float
    sl_price:    float
    tp1_price:   float  # entry ± sl_dist × 3
    tp2_price:   float  # entry ± sl_dist × 5
    tp3_price:   float  # entry ± sl_dist × 8
    entry_size:  float  # реальный $ входа
    qty:         float  # количество монет
    max_loss:    float  # $ убытка при SL
    sl_pct:      float  # % до SL
    tp1_pct:     float  # % до TP1
    rr_ratio:    float  # = config.MIN_RR_RATIO (всегда 3)
    is_valid:    bool
    warning:     str    # "" или описание проблемы
```

```python
calculate(direction, entry_price, sl_price=None, atr=None,
          nearest_support=None, nearest_resistance=None) -> TradeSetup
# Автоматический SL (если sl_price=None), приоритет:
#   1. Ближайший уровень поддержки/сопротивления × 0.998 (буфер 0.2%)
#   2. entry_price ± ATR × 1.5
#   3. entry_price × (1 ± MAX_LOSS_PER_TRADE/ENTRY_SIZE)
#
# qty рассчитывается как MAX_LOSS / sl_dist
# Если qty × entry_price > ENTRY_SIZE → qty = ENTRY_SIZE / entry_price (ограничение)
#
# warning генерируется если:
#   sl_pct > 15% → "SL очень далеко"
#   sl_pct < 0.3% → "SL очень близко"

to_dict(setup: TradeSetup) -> dict
# Конвертирует TradeSetup в словарь для API и Claude контекста
```

---

## analysis/sentiment/reddit.py

```python
async fetch_sentiment(symbol: str, limit_per_sub=10) -> RedditSentiment
# Ищет тикер (BTC из "BTC/USDT") в 6 сабреддитах:
# CryptoCurrency, CryptoMarkets, altcoin, ethtrader, Bitcoin, SatoshiStreetBets
# Метод поиска: subreddit.search(ticker, sort="new", time_filter="day")
# Фильтрация: пост должен содержать тикер в тексте
# Скоринг по ключевым словам (BULLISH_WORDS / BEARISH_WORDS)
# Взвешивание по upvote score (weight *= max(1, upvotes/100))
#
# Если REDDIT_CLIENT_ID не задан → возвращает RedditSentiment с error
# Если ошибка сети/API → логирует предупреждение, продолжает со следующим сабреддитом
#
# Возвращает RedditSentiment:
# {symbol, posts, total_posts, bullish_count, bearish_count, neutral_count,
#  score: float(-1..+1), label: "bullish"|"bearish"|"neutral", top_titles, error}

to_dict(sent: RedditSentiment) -> dict
# Сериализует в plain dict для API
```

---

## analysis/sentiment/scorer.py

```python
aggregate(reddit: RedditSentiment) -> dict
# Агрегирует Reddit сентимент в итоговый dict:
# {
#   "score": float(-1..+1),
#   "label": "bullish"|"bearish"|"neutral",
#   "confidence": "high"|"medium"|"low",  # high: >=15 постов, medium: >=5
#   "summary": str,
#   "sources": {"reddit": {...}},
# }
# Если reddit.error или 0 постов → confidence="low", summary = текст ошибки

from_ta_signal(ta_signal: dict) -> dict
# Фоллбэк: строит сентимент из TA сигнала когда Reddit недоступен.
# Нормализует score (-100..+100) → (-1..+1)
# Возвращает тот же формат что aggregate()
# sources содержит: {"reddit": {error: "Reddit недоступен..."}, "ta_fallback": {...}}
```

> **Логика фоллбэка в `agent/recommender.py`:**
> ```python
> reddit_ok = not isinstance(reddit, Exception) and not getattr(reddit, "error", None)
> if reddit_ok:
>     sentiment_agg = sent_aggregate(reddit)
> else:
>     sentiment_agg = sent_from_ta(signal)   # TA-based fallback
> ```

---

## agent/prompts.py

Два шаблона строк с `{...}` плейсхолдерами:

- **`SYSTEM_TRADING`** — системный промт для торговых рекомендаций. Содержит правила риска (форматируются из config), требует обязательный блок `---РЕКОМЕНДАЦИЯ---` в ответе. Язык: русский.
- **`SYSTEM_SESSION`** — системный промт для пре-сессионного чека. Включает дневной P&L и количество сделок.

---

## agent/claude_agent.py

### Класс `TradingAgent`

```python
agent = get_agent()   # синглтон
```

```python
build_trade_context(symbol, market, timeframe, ticker, signal, risk,
                    sentiment=None, ob=None) -> str
# Собирает текстовый контекст для Claude из всех источников данных.
# Секции: ТЕКУЩАЯ ЦЕНА, СТАКАН, ТЕХНИЧЕСКИЙ АНАЛИЗ, УРОВНИ, СЕНТИМЕНТ REDDIT, РАСЧЁТ РИСКА
# sentiment включается только если нет sentiment["error"]

analyze(context: str) -> str
# Синхронный запрос к Claude (claude-sonnet-4-6), max_tokens=1500
# НЕ поддерживает stream=True (выбросит ValueError)

analyze_stream(context: str) -> Generator[str, None, None]
# Потоковый генератор. Используется в SSE эндпоинте.
# Yields: текстовые чанки по мере генерации Claude

session_check(emotional_score, user_notes, pnl, trades) -> str
# Вызов Claude с SYSTEM_SESSION промтом.
# max_tokens=600. Возвращает текстовый совет.
```

---

## agent/recommender.py

```python
async build_recommendation(symbol, market, timeframe, exchange) -> dict
# Полный pipeline рекомендации:
# 1. Параллельно (asyncio.gather):
#    - get_ticker()
#    - OrderBookAnalyzer.analyze()
#    - get_ohlcv_df()
#    - fetch_sentiment()
# 2. ta_signals.generate(df)
# 3. risk_calc.calculate()
# 4. sent_aggregate() или sent_from_ta() (если Reddit недоступен)
# 5. agent.build_trade_context() + agent.analyze()
# 6. _save_recommendation() → БД
#
# Обработка ошибок:
#   ticker ошибка → raise (критично)
#   ob ошибка    → ob = None (некритично)
#   df ошибка    → raise (критично)
#   reddit ошибка → fallback на TA
#
# Возвращает:
# {"symbol", "market", "timeframe", "ticker", "signal", "risk",
#  "sentiment", "claude", "ob"}

_save_recommendation(symbol, market, signal, risk, text) -> None
# Сохраняет в таблицу recommendations.
# Сохраняется только если risk.is_valid=True и direction != "neutral"
# reasoning обрезается до 2000 символов
```

---

## web/app.py

```python
app = FastAPI(lifespan=lifespan)
# lifespan: init_db() + GateExchange() + проверочный тикер BTC/USDT
# При остановке: exchange.close()

get_exchange() -> GateExchange
# Возвращает глобальный синглтон _exchange
# RuntimeError если не инициализирован (не должно происходить после старта)
```

### Маршруты

| Prefix | Роутер | Файл |
|---|---|---|
| `/` | dashboard | `web/routers/dashboard.py` |
| `/api/market` | market | `web/routers/market.py` |
| `/session` | session | `web/routers/session.py` |
| `/agent` | agent | `web/routers/agent.py` |
| `/positions` | positions | `web/routers/positions.py` |
| `/settings` | settings | `web/routers/settings.py` |

---

## web/routers/dashboard.py

```python
GET /                      # Дашборд — HTML
# Передаёт в шаблон: stats, pnl, limit, remaining, used_pct, blocked,
#                    entry_size, max_loss, rr_ratio, tp1/2/3, max_trades

GET /screener              # Страница скринера — HTML

GET /analysis              # Страница анализа — HTML
# Query: symbol="BTC/USDT", market="spot"
```

---

## web/routers/market.py

```python
GET /api/market/stats -> StatsResponse
# {trade_date, realized_pnl, trades_count, losses_count,
#  session_blocked, remaining, used_pct}
# Используется фронтендом для polling каждые 30с

GET /api/market/ticker?symbol=BTC/USDT&market=spot -> TickerResponse
# Проксирует exchange.get_ticker()

GET /api/market/orderbook?symbol=&market=spot&depth=20 -> OrderBookResponse
# Проксирует OrderBookAnalyzer.analyze() + liquidity_verdict()

GET /api/market/ta?symbol=&market=spot&timeframe=5m&limit=200
# Полный ТА: OHLCV → signals.generate() + risk_calc.calculate()
# Возвращает: {"symbol", "market", "timeframe", "signal": {...}, "risk": {...}}

GET /api/market/screener?market=spot&top_n=20&min_volume=500000&liquidity=all&pattern=&timeframe=1h
# liquidity: "all" | "liquid" (спред ≤0.3%) | "illiquid" (спред >1%)
# pattern: "" | "bullish" | "bearish" | "hammer" | "shooting_star" | "doji" |
#           "engulfing" | "marubozu" | "morning_star" | "evening_star"
# При liquidity≠all: параллельные запросы стакана (10 уровней) для каждой монеты
# При pattern: батчи по 5 монет, OHLCV → detect_patterns() для каждой
# Если оба фильтра — сначала liquidity, потом pattern по отфильтрованному списку
# Возвращает: {"data": [...тикеры + опционально spread_pct, matched_pattern, direction], "count": int}
```

---

## web/routers/session.py

```python
GET /session/              # Форма — HTML (result=None)

POST /session/             # Обработка формы — HTML
# Form params: score (1-10), notes (str, optional)
# Логика:
#   score >= 8 → "Отличное", green, allowed=True
#   score >= 6 → "Нормальное", yellow, allowed=True
#   score >= 4 → "Ниже нормы", orange, allowed=True
#   score < 4  → "Плохое", red, allowed=False
# Затем пробует вызвать TradingAgent.session_check() — если ошибка, claude_advice=None
# Рендерит session.html с result={"score", "verdict", "color", "allowed",
#                                  "tips", "notes", "claude_advice"}
```

---

## web/routers/agent.py

```python
GET /agent/recommend?symbol=BTC/USDT&market=spot&timeframe=5m
# HTML страница recommend.html — SSE клиент

GET /agent/stream?symbol=&market=spot&timeframe=5m
# Server-Sent Events (text/event-stream)
# Последовательность событий:
#   event: status   data: "⏳ Загружаю рыночные данные..."
#   event: data     data: JSON {ticker, signal, risk, sentiment, ob}
#   event: status   data: "🤖 Claude анализирует..."
#   event: claude   data: <текстовый чанк> (повторяется)
#   event: done     data: "ok"
#   event: error    data: <сообщение об ошибке>
# Важно: Claude стриминг выполняется в executor (loop.run_in_executor),
# так как anthropic SDK синхронный

POST /agent/session?score=7&notes=...
# Query params (не body!): score (int 1-10), notes (str)
# Вызывает TradingAgent.session_check()
# Возвращает: {"advice": str, "score": int}

GET /agent/history?limit=20
# Последние рекомендации из таблицы recommendations
# Возвращает: {"data": [dict, ...]}
```

---

## web/routers/positions.py

```python
GET /positions/            # HTML страница positions.html

GET /positions/api/list?market_type=futures
# Возвращает: {"positions": [...], "count": int}
# Данные из exchange.get_positions()

GET /positions/api/orders?symbol=&market_type=spot
# Открытые ордера. symbol опционален.
# Возвращает: {"orders": [...], "count": int}

POST /positions/api/order
# Body (JSON): {symbol, side, amount, price?, order_type="limit", market_type="spot"}
# Возвращает: {"ok": true, "order": {...}}

POST /positions/api/close
# Body (JSON): {symbol, side, amount, market_type="futures"}
# Возвращает: {"ok": true, "order": {...}}

POST /positions/api/cancel
# Body (JSON): {order_id, symbol, market_type="spot"}
# Возвращает: {"ok": true, "result": {...}}
```

---

## web/routers/settings.py

```python
GET /settings/             # HTML страница settings.html
# Передаёт cfg = {entry_size, max_loss_per_trade, daily_drawdown_limit, min_rr_ratio}

GET /settings/api/current
# Текущие значения + вычисляемые tp1/2/3 и max_trades
# Возвращает: {entry_size, max_loss_per_trade, daily_drawdown_limit, min_rr_ratio,
#              tp1, tp2, tp3, max_trades}

POST /settings/api/update
# Body (JSON): {entry_size, max_loss_per_trade, daily_drawdown_limit, min_rr_ratio}
# Действия:
#   1. Немедленно присваивает config.ENTRY_SIZE = req.entry_size и т.д.
#   2. Вызывает _update_env() — перезаписывает строки в .env файле
#      (ошибка записи в .env не критична — изменения уже в памяти)
# Возвращает: {"ok": true, "message": str, "settings": {...}}
```

### Функция `_update_env(updates: dict[str, str])`

Читает `.env` построчно, заменяет значения ключей из `updates`, дописывает новые ключи в конец. Создаёт `.env` если файл не существует.

---

## web/templates — страницы

### `base.html`
Навигация: Дашборд → `/` | Скринер → `/screener` | Анализ → `/analysis` | 📊 Позиции → `/positions` | 🤖 Агент → `/agent/recommend` | Чек сессии → `/session` | ⚙️ Риски → `/settings`  
Подключает `/static/css/style.css` и `/static/js/main.js`.  
Polling `/api/market/stats` каждые 30 секунд (точка подключения в навбаре).

### `dashboard.html`
- 4 карточки: P&L сегодня, Осталось до лимита, Кол-во сделок, Статус сессии
- Прогресс-бар дневной просадки (зелёный < 40%, жёлтый < 70%, красный >= 70%)
- Таблица правил входа (размер, SL, R:R, TP1/2/3, макс. стоп-лоссов)
- Быстрые действия: кнопки со ссылками (задизейблены при `blocked=True`)
- Быстрый тикер: `input + select(spot/futures) → GET /api/market/ticker`

### `screener.html`
- Фильтры: Рынок, Топ-N, Мин. объём
- Расширенные: Ликвидность (все/ликвидные/неликвиды), ТА паттерн, Таймфрейм
- Предупреждение при активации медленных фильтров
- Таблица с динамическими колонками (spread_pct и matched_pattern — если возвращены API)

### `analysis.html`
- Автозапуск при загрузке (`symbol` из URL-параметра)
- Запросы: `/api/market/ticker` + `/api/market/orderbook` + `/api/market/ta`
- Блоки: Тикер, Стакан, ТА-сигнал (direction+score+confidence), Расчёт риска, Индикаторы (grid), Паттерны (badges)

### `recommend.html`
- EventSource → `GET /agent/stream`
- Рендерит карточки данных (тикер, сигнал, сентимент, риск, стакан)
- Текст Claude стримится чанк за чанком в `.claude-output` div

### `session.html`
- Форма: радио-кнопки 1–10, textarea заметок, POST /session/
- Результат: score-display (цвет по color), verdict, список tips, claude_advice (если доступен)

### `positions.html`
- Переключатель `Фьючерсы / Спот` → `GET /positions/api/list?market_type=`
- Переключатель `$ / %` для P&L на всех карточках
- Карточки позиций (`pos-card`, `pos-long`/`pos-short`) с данными и кнопками
- Клик на карточку → показывает мини-стакан (`GET /api/market/orderbook`), обновляется каждые 5с
- Таблица открытых ордеров с кнопкой отмены
- Модальное окно «Закрыть позицию» → `POST /positions/api/close`
- Модальное окно «Лимитная заявка» → `POST /positions/api/order`

### `settings.html`
- Форма с 4 полями + предпросмотр в реальном времени (JS обновляет таблицу при вводе)
- `POST /settings/api/update` → применяет немедленно

---

## web/static/js/main.js

```javascript
fmtPrice(price: number) -> string
// Форматирует цену с подходящим числом знаков:
// >= 1000 → 2 знака (например: 43,512.34)
// >= 1    → 4 знака
// < 1     → 6 знаков (для альткоинов)

fmtVol(vol: number) -> string
// >= 1e9 → "1.2B$"
// >= 1e6 → "1.2M$"
// >= 1e3 → "123K$"
// иначе  → "123$"

checkConnection()
// Polling /api/market/stats каждые 30 секунд
// Обновляет #conn-dot (зелёный/красный) и #conn-label
```

---

## SQLite — типичные запросы для отладки

```sql
-- Текущая дневная статистика
SELECT * FROM daily_stats ORDER BY trade_date DESC LIMIT 5;

-- Последние рекомендации
SELECT id, created_at, symbol, direction, entry_price, sl_price,
       tp1_price, rr_ratio, status
FROM recommendations
ORDER BY created_at DESC LIMIT 10;

-- Разблокировать сессию вручную
UPDATE daily_stats SET session_blocked = 0 WHERE trade_date = date('now');

-- Сбросить дневной P&L
UPDATE daily_stats SET realized_pnl = 0, trades_count = 0, losses_count = 0
WHERE trade_date = date('now');
```

---

## Типичные ошибки и их причины

| Ошибка | Причина | Решение |
|---|---|---|
| `RuntimeError: Exchange not initialized` | `get_exchange()` вызван до старта FastAPI lifespan | Убедиться что сервер запущен через `python main.py web` |
| `ValueError: Символ 'XYZ' не найден` | Символ не существует на Gate.io | Проверить через `/api/market/screener` |
| `ValueError: Для лимитного ордера необходима цена` | `POST /positions/api/order` без поля `price` при `order_type=limit` | Передать `price` в теле запроса |
| Reddit сентимент пустой | `REDDIT_CLIENT_ID` не задан → автоматический fallback на TA | Нормальное поведение, не ошибка |
| Claude не отвечает | `ANTHROPIC_API_KEY` не задан или недействителен | Проверить `.env` |
| `session_blocked = 1` | `realized_pnl <= -DAILY_DRAWDOWN_LIMIT` | SQL: `UPDATE daily_stats SET session_blocked=0...` |
| Screener с паттернами зависает | Слишком много монет × OHLCV запросов | Уменьшить `top_n` или увеличить `min_volume` |
| `get_positions("spot")` возвращает пустой список | API ключ без прав на чтение баланса | Проверить права ключа Gate.io |

---

## Зависимости (requirements.txt — актуальные версии)

```
fastapi==0.115.12
uvicorn==0.34.2
jinja2==3.1.6
python-multipart==0.0.20
ccxt==4.5.46
pandas==2.2.3
numpy==2.2.1
anthropic==0.89.0
praw==7.8.1
python-dotenv==1.0.1
sqlalchemy==2.0.49
aiohttp==3.13.5
rich==14.3.3
python-telegram-bot==22.7
```

> **Примечание:** `pandas-ta` НЕ используется. Все индикаторы реализованы через чистый pandas/numpy в `analysis/technical/indicators.py`.
