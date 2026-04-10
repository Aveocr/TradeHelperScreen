# AI Trading Assistant

Локальный веб-ассистент для скальпинга и внутридневной торговли на Gate.io.  
Анализирует рынок, генерирует рекомендации через Claude AI и отслеживает риски.

---

## Стек

| Слой | Технологии |
|---|---|
| Бэкенд | Python 3.11+, FastAPI, uvicorn |
| Биржа | ccxt async (Gate.io spot + futures) |
| AI | Anthropic Claude (claude-sonnet-4-6) |
| Анализ | pandas, ta, numpy |
| Сентимент | PRAW (Reddit) |
| БД | SQLite (SQLAlchemy) |
| UI | Jinja2 + vanilla JS, dark theme |

---

## Возможности

- **Скринер рынка** — быстрый поиск монет по объёму (ликвидные / неликвидные < 2M$/сут)
- **Технический анализ** — EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, VWAP, свечные паттерны, уровни поддержки/сопротивления
- **Рекомендации Claude** — точка входа, SL, TP1/TP2/TP3, R:R ≥ 3:1, обоснование
- **Риск-менеджмент** — макс. убыток $1 на сделку, дневной лимит просадки $6
- **Позиции** — баланс spot/futures, открытые позиции Gate.io в реальном времени
- **Журнал PNL** — фиксация результатов сделок, статистика сессии
- **Session check** — оценка эмоционального состояния трейдера через Claude
- **CLI режим** — альтернатива веб-интерфейсу через Rich-терминал

---

## Установка

```bash
git clone <repo>
cd AI-trade-assistante

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### Настройка `.env`

Создайте файл `.env` в корне проекта:

```env
# Обязательные
GATE_API_KEY=your_gate_api_key
GATE_API_SECRET=your_gate_api_secret
ANTHROPIC_API_KEY=your_anthropic_api_key

# Опциональные (Reddit сентимент)
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=TradingBot/1.0

# Параметры риска (defaults)
ENTRY_SIZE=10.0
MAX_LOSS_PER_TRADE=1.0
DAILY_DRAWDOWN_LIMIT=6.0
MIN_RR_RATIO=3.0
```

---

## Запуск

```bash
# Веб-интерфейс (http://127.0.0.1:8000)
python main.py web

# CLI режим
python main.py cli
```

---

## Структура проекта

```
AI-trade-assistante/
├── main.py                  # точка входа
├── .env                     # ключи (не в git)
├── requirements.txt
│
├── core/
│   ├── config.py            # Config singleton, параметры риска
│   ├── database.py          # SQLite: recommendations, daily_stats, session_logs
│   └── logger.py            # Rich + файловый лог
│
├── exchanges/
│   └── gate.py              # GateExchange (ccxt async) — spot + futures
│
├── data/
│   ├── market_data.py       # MarketDataService: OHLCV + скринер
│   └── orderbook.py         # OrderBookAnalyzer: ликвидность, кластеры
│
├── analysis/
│   ├── technical/           # indicators, patterns, levels, signals (-100..+100)
│   └── sentiment/           # Reddit парсер + fallback на TA
│
├── risk/
│   └── calculator.py        # TradeSetup: SL, TP1/2/3, qty, R:R
│
├── agent/
│   ├── claude_agent.py      # TradingAgent: analyze(), session_check()
│   ├── recommender.py       # build_recommendation(): полный pipeline
│   └── prompts.py           # системные промпты Claude
│
├── web/
│   ├── app.py               # FastAPI app
│   ├── routers/             # dashboard, market, session, agent, positions, settings
│   ├── templates/           # Jinja2 HTML
│   └── static/              # CSS (dark theme) + JS
│
└── ui/
    └── cli.py               # Rich CLI
```

---

## API эндпоинты (основные)

| Метод | Путь | Описание |
|---|---|---|
| GET | `/` | Дашборд |
| GET | `/screener` | Скринер рынка |
| GET | `/analysis` | Технический анализ |
| GET | `/positions/` | Позиции и баланс |
| GET | `/session/` | Сессия трейдера |
| GET | `/settings/` | Настройки риска |
| GET | `/api/market/screener` | Скринер (JSON) |
| GET | `/api/market/ta` | Технический анализ (JSON) |
| POST | `/api/market/pnl` | Зафиксировать результат сделки |
| GET | `/positions/api/balance` | Баланс spot/futures |
| GET | `/agent/recommend` | Рекомендация Claude (JSON) |
| GET | `/agent/stream` | Рекомендация Claude (SSE стрим) |
| POST | `/settings/api/update` | Обновить параметры риска |

---

## Параметры риска

Изменяются в рантайме через страницу `/settings/` без перезапуска сервера.

| Параметр | Default | Описание |
|---|---|---|
| `ENTRY_SIZE` | $10 | Размер входа в сделку |
| `MAX_LOSS_PER_TRADE` | $1 | Макс. убыток на сделку |
| `DAILY_DRAWDOWN_LIMIT` | $6 | Дневной лимит просадки |
| `MIN_RR_RATIO` | 3.0 | Минимальный R:R |
