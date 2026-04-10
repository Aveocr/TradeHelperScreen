"""
FastAPI веб-приложение AI Trading Assistant.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core.config import config
from core.database import init_db
from core.logger import get_logger
from exchanges.gate import GateExchange

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent

# Глобальный экземпляр биржи (переиспользуется между запросами)
_exchange: GateExchange | None = None


def get_exchange() -> GateExchange:
    if _exchange is None:
        raise RuntimeError("Exchange not initialized")
    return _exchange


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация и завершение при старте/остановке сервера."""
    global _exchange

    init_db()
    _exchange = GateExchange()

    try:
        ticker = await _exchange.get_ticker("BTC/USDT", market_type="spot")
        logger.info(f"Gate.io подключён | BTC/USDT: {ticker['last']:,.2f}$")
    except Exception as e:
        logger.error(f"Ошибка подключения к Gate.io: {e}")

    logger.info("Веб-сервер запущен → http://127.0.0.1:8000")
    yield

    if _exchange:
        await _exchange.close()
    logger.info("Веб-сервер остановлен")


app = FastAPI(
    title="AI Trading Assistant",
    description="Торговый помощник на базе Gate.io + Claude AI",
    version="1.0.0",
    lifespan=lifespan,
)

# Статика и шаблоны
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Роутеры
from web.routers import dashboard, market, session, agent, positions, settings  # noqa: E402

app.include_router(dashboard.router)
app.include_router(market.router,     prefix="/api/market")
app.include_router(session.router,    prefix="/session")
app.include_router(agent.router,      prefix="/agent")
app.include_router(positions.router,  prefix="/positions")
app.include_router(settings.router,   prefix="/settings")
