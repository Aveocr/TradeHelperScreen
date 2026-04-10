from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core.config import config
from core.database import get_today_stats, is_session_blocked

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = get_today_stats()
    pnl = stats["realized_pnl"]
    limit = config.DAILY_DRAWDOWN_LIMIT
    used_pct = min(abs(pnl) / limit * 100, 100) if pnl < 0 else 0

    return templates.TemplateResponse("dashboard.html", {
        "request":       request,
        "stats":         stats,
        "pnl":           pnl,
        "pnl_sign":      "+" if pnl >= 0 else "",
        "limit":         limit,
        "remaining":     round(limit + pnl, 2),
        "used_pct":      round(used_pct, 1),
        "blocked":       is_session_blocked(),
        "entry_size":    config.ENTRY_SIZE,
        "max_loss":      config.MAX_LOSS_PER_TRADE,
        "rr_ratio":      config.MIN_RR_RATIO,
        "tp1":           config.MAX_LOSS_PER_TRADE * 3,
        "tp2":           config.MAX_LOSS_PER_TRADE * 5,
        "tp3":           config.MAX_LOSS_PER_TRADE * 8,
        "max_trades":    int(config.DAILY_DRAWDOWN_LIMIT / config.MAX_LOSS_PER_TRADE),
    })


@router.get("/screener", response_class=HTMLResponse)
async def screener_page(request: Request):
    return templates.TemplateResponse("screener.html", {"request": request})


@router.get("/analysis", response_class=HTMLResponse)
async def analysis_page(request: Request, symbol: str = "BTC/USDT", market: str = "spot"):
    return templates.TemplateResponse("analysis.html", {
        "request":     request,
        "symbol":      symbol,
        "market_type": market,
    })
