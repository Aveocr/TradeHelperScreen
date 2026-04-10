"""
Роутер настроек риска — позволяет менять параметры через веб-интерфейс.
Изменения применяются немедленно в памяти и сохраняются в .env файл.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from core.config import config

router = APIRouter(tags=["settings"])
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")

_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class RiskSettings(BaseModel):
    entry_size:           float = Field(gt=0, description="Размер входа в USDT")
    max_loss_per_trade:   float = Field(gt=0, description="Макс. убыток за сделку в USDT")
    daily_drawdown_limit: float = Field(gt=0, description="Дневной лимит просадки в USDT")
    min_rr_ratio:         float = Field(ge=1, description="Минимальный R:R")


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "cfg": {
            "entry_size":           config.ENTRY_SIZE,
            "max_loss_per_trade":   config.MAX_LOSS_PER_TRADE,
            "daily_drawdown_limit": config.DAILY_DRAWDOWN_LIMIT,
            "min_rr_ratio":         config.MIN_RR_RATIO,
        }
    })


@router.get("/api/current")
async def get_current_settings():
    """Текущие настройки риска."""
    return {
        "entry_size":           config.ENTRY_SIZE,
        "max_loss_per_trade":   config.MAX_LOSS_PER_TRADE,
        "daily_drawdown_limit": config.DAILY_DRAWDOWN_LIMIT,
        "min_rr_ratio":         config.MIN_RR_RATIO,
        "tp1":                  round(config.MAX_LOSS_PER_TRADE * 3, 2),
        "tp2":                  round(config.MAX_LOSS_PER_TRADE * 5, 2),
        "tp3":                  round(config.MAX_LOSS_PER_TRADE * 8, 2),
        "max_trades":           int(config.DAILY_DRAWDOWN_LIMIT / config.MAX_LOSS_PER_TRADE),
    }


@router.post("/api/update")
async def update_settings(req: RiskSettings):
    """
    Обновляет настройки риска:
    1. Применяет мгновенно к объекту config в памяти
    2. Перезаписывает соответствующие строки в .env
    """
    # Применяем в памяти
    config.ENTRY_SIZE           = req.entry_size
    config.MAX_LOSS_PER_TRADE   = req.max_loss_per_trade
    config.DAILY_DRAWDOWN_LIMIT = req.daily_drawdown_limit
    config.MIN_RR_RATIO         = req.min_rr_ratio

    # Сохраняем в .env
    try:
        _update_env({
            "ENTRY_SIZE":           str(req.entry_size),
            "MAX_LOSS_PER_TRADE":   str(req.max_loss_per_trade),
            "DAILY_DRAWDOWN_LIMIT": str(req.daily_drawdown_limit),
            "MIN_RR_RATIO":         str(req.min_rr_ratio),
        })
    except Exception as e:
        # Не критично — изменения уже применены в памяти
        pass

    return {
        "ok": True,
        "message": "Настройки обновлены",
        "settings": {
            "entry_size":           config.ENTRY_SIZE,
            "max_loss_per_trade":   config.MAX_LOSS_PER_TRADE,
            "daily_drawdown_limit": config.DAILY_DRAWDOWN_LIMIT,
            "min_rr_ratio":         config.MIN_RR_RATIO,
        }
    }


def _update_env(updates: dict[str, str]) -> None:
    """Обновляет или добавляет ключи в .env файл."""
    if not _ENV_PATH.exists():
        # Создаём .env если не существует
        lines = [f"{k}={v}\n" for k, v in updates.items()]
        _ENV_PATH.write_text("".join(lines), encoding="utf-8")
        return

    existing = _ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in existing:
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            new_lines.append(f"{key}={updates[key]}\n")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    # Добавляем новые ключи, которых не было
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")

    _ENV_PATH.write_text("".join(new_lines), encoding="utf-8")
