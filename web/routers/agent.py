"""
API роутер для Claude AI агента.
GET  /agent/recommend  — полная рекомендация (JSON)
GET  /agent/stream     — потоковая рекомендация (SSE)
POST /agent/session    — пре-сессионный чек с Claude
GET  /agent/history    — история рекомендаций из БД
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from fastapi.responses import HTMLResponse

from core.config import config
from core.database import get_today_stats, get_conn
from agent.recommender import build_recommendation
from agent.claude_agent import get_agent
from web.app import get_exchange

router = APIRouter(tags=["agent"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


# ── Страница рекомендации ─────────────────────────────────────────────────────

@router.get("/recommend", response_class=HTMLResponse)
async def recommend_page(request: Request,
                         symbol: str = "BTC/USDT",
                         market: str = "spot",
                         timeframe: str = "5m"):
    return templates.TemplateResponse("recommend.html", {
        "request":   request,
        "symbol":    symbol,
        "market":    market,
        "timeframe": timeframe,
    })


# ── SSE стриминг рекомендации ─────────────────────────────────────────────────

@router.get("/stream")
async def stream_recommend(
    symbol:    str = Query(default="BTC/USDT"),
    market:    str = Query(default="spot"),
    timeframe: str = Query(default="5m"),
):
    """
    Server-Sent Events: отдаёт данные и текст Claude по мере генерации.
    Фронтенд подписывается через EventSource.
    """
    exchange = get_exchange()

    async def event_generator():
        try:
            # Шаг 1: Собираем все данные
            yield _sse("status", "⏳ Загружаю рыночные данные...")
            await asyncio.sleep(0)

            result = await build_recommendation(symbol, market, timeframe, exchange)

            # Отправляем структурированные данные
            yield _sse("data", json.dumps({
                "ticker":    result["ticker"],
                "signal":    result["signal"],
                "risk":      result["risk"],
                "sentiment": result["sentiment"],
                "ob":        result.get("ob"),
            }, ensure_ascii=False))

            yield _sse("status", "🤖 Claude анализирует...")
            await asyncio.sleep(0)

            # Шаг 2: Стриминг ответа Claude
            agent   = get_agent()
            context = agent.build_trade_context(
                symbol    = symbol,
                market    = market,
                timeframe = timeframe,
                ticker    = result["ticker"],
                signal    = result["signal"],
                risk      = result["risk"],
                sentiment = result["sentiment"],
                ob        = result.get("ob"),
            )

            # Стриминг через поток Claude
            loop = asyncio.get_running_loop()
            buffer = []

            def _stream_sync():
                for chunk in agent.analyze_stream(context):
                    buffer.append(chunk)

            await loop.run_in_executor(None, _stream_sync)

            # Отправляем буфер чанками
            for chunk in buffer:
                yield _sse("claude", chunk)
                await asyncio.sleep(0)

            yield _sse("done", "ok")

        except Exception as e:
            yield _sse("error", str(e))

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


# ── Пре-сессионный чек с Claude ───────────────────────────────────────────────

@router.post("/session")
async def session_check_claude(
    score: int = Query(..., ge=1, le=10),
    notes: str = Query(default=""),
):
    """Claude анализирует эмоциональное состояние и даёт советы."""
    stats = get_today_stats()
    try:
        agent  = get_agent()
        loop   = asyncio.get_running_loop()
        advice = await loop.run_in_executor(
            None,
            lambda: agent.session_check(
                emotional_score = score,
                user_notes      = notes,
                pnl             = stats["realized_pnl"],
                trades          = stats["trades_count"],
            )
        )
        return {"advice": advice, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка Claude: {e}")


# ── История рекомендаций ──────────────────────────────────────────────────────

@router.get("/history")
async def get_history(limit: int = Query(default=20, ge=1, le=100)):
    """Последние рекомендации из БД."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM recommendations ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return {"data": [dict(r) for r in rows]}
