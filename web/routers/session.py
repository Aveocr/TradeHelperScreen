from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["session"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def session_form(request: Request):
    return templates.TemplateResponse("session.html", {
        "request": request,
        "result": None,
    })


@router.post("/", response_class=HTMLResponse)
async def session_submit(
    request: Request,
    score: int = Form(...),
    notes: str = Form(default=""),
):
    if score >= 8:
        verdict = "Отличное состояние! Торговать можно. Придерживайся плана."
        color = "green"
        allowed = True
        tips = [
            "Ставь стоп-лоссы до входа в позицию.",
            "Не увеличивай размер сделки после серии профитов.",
            "Торгуй по плану, не по эмоциям.",
        ]
    elif score >= 6:
        verdict = "Нормальное состояние. Торгуй осторожно."
        color = "yellow"
        allowed = True
        tips = [
            "Сократи количество сделок — только А+ сетапы.",
            "Сделай паузу после каждого стоп-лосса.",
            "Не торопись — хорошая точка входа появится снова.",
        ]
    elif score >= 4:
        verdict = "Состояние ниже нормы. Рекомендуется сократить риск вдвое."
        color = "orange"
        allowed = True
        tips = [
            "Уменьши размер сделок до 50% от обычного.",
            "Установи личный лимит: не более 2 сделок.",
            "Если получил 1 стоп-лосс — остановись на 1 час.",
        ]
    else:
        verdict = "Плохое состояние. Торговля не рекомендована сегодня."
        color = "red"
        allowed = False
        tips = [
            "Отдохни и вернись завтра с ясной головой.",
            "Просмотри свои прошлые сделки для обучения.",
            "Помни: сохранить капитал — тоже результат.",
        ]

    # Пробуем получить совет от Claude
    claude_advice = None
    try:
        import asyncio
        from agent.claude_agent import get_agent
        from core.database import get_today_stats
        stats = get_today_stats()
        agent = get_agent()
        loop = asyncio.get_running_loop()
        claude_advice = await loop.run_in_executor(
            None,
            lambda: agent.session_check(
                emotional_score = score,
                user_notes      = notes,
                pnl             = stats["realized_pnl"],
                trades          = stats["trades_count"],
            )
        )
    except Exception:
        pass  # Claude недоступен — используем базовую логику

    return templates.TemplateResponse("session.html", {
        "request": request,
        "result": {
            "score":         score,
            "verdict":       verdict,
            "color":         color,
            "allowed":       allowed,
            "tips":          tips,
            "notes":         notes,
            "claude_advice": claude_advice,
        },
    })
