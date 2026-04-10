"""
Роутер позиций: просмотр открытых позиций, закрытие, лимитные ордера.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from web.app import get_exchange

router = APIRouter(tags=["positions"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


# ── Схемы ─────────────────────────────────────────────────────────────────────

class PlaceOrderRequest(BaseModel):
    symbol:      str
    side:        str          # buy / sell
    amount:      float
    price:       float | None = None
    order_type:  str = "limit"   # limit / market
    market_type: str = "spot"


class ClosePositionRequest(BaseModel):
    symbol:      str
    side:        str          # long / short
    amount:      float
    market_type: str = "futures"


class CancelOrderRequest(BaseModel):
    order_id:    str
    symbol:      str
    market_type: str = "spot"


# ── Страница ──────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def positions_page(request: Request):
    return templates.TemplateResponse("positions.html", {"request": request})


# ── API ───────────────────────────────────────────────────────────────────────

@router.get("/api/balance")
async def get_balance(
    market_type: str = Query(default="spot"),
):
    """Полный баланс аккаунта (включая USDT)."""
    exchange = get_exchange()
    try:
        balance = await exchange.get_balance(market_type)
        return balance
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")


@router.get("/api/list")
async def list_positions(
    market_type: str = Query(default="futures"),
):
    """Список открытых позиций (фьючерсы) или ненулевых балансов (спот)."""
    exchange = get_exchange()
    try:
        positions = await exchange.get_positions(market_type)
        return {"positions": positions, "count": len(positions)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")


@router.get("/api/orders")
async def list_orders(
    symbol: str | None = Query(default=None),
    market_type: str   = Query(default="spot"),
):
    """Список открытых ордеров."""
    exchange = get_exchange()
    try:
        orders = await exchange.get_open_orders(symbol, market_type)
        return {"orders": orders, "count": len(orders)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")


@router.post("/api/order")
async def place_order(req: PlaceOrderRequest):
    """Размещает лимитный или рыночный ордер."""
    exchange = get_exchange()
    try:
        result = await exchange.place_order(
            symbol=req.symbol,
            side=req.side.lower(),
            amount=req.amount,
            price=req.price,
            order_type=req.order_type,
            market_type=req.market_type,
        )
        return {"ok": True, "order": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")


@router.post("/api/close")
async def close_position(req: ClosePositionRequest):
    """Закрывает позицию по рынку."""
    exchange = get_exchange()
    try:
        result = await exchange.close_position_market(
            symbol=req.symbol,
            side=req.side.lower(),
            amount=req.amount,
            market_type=req.market_type,
        )
        return {"ok": True, "order": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")


@router.post("/api/cancel")
async def cancel_order(req: CancelOrderRequest):
    """Отменяет открытый ордер."""
    exchange = get_exchange()
    try:
        result = await exchange.cancel_order(
            order_id=req.order_id,
            symbol=req.symbol,
            market_type=req.market_type,
        )
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ошибка Gate.io: {e}")
