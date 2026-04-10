"""
AI Trading Assistant — точка входа.
Запускает веб-сервер FastAPI или CLI в зависимости от аргументов.

Запуск веб-интерфейса:
    python main.py web

Запуск CLI:
    python main.py cli
"""

from __future__ import annotations

import sys
import asyncio

from rich.console import Console

console = Console()


def run_web():
    """Запускает FastAPI веб-сервер через uvicorn."""
    import uvicorn
    from core.config import config

    try:
        config.validate()
    except EnvironmentError as e:
        console.print(f"\n[red]{e}[/red]\n")
        sys.exit(1)

    console.print("[blue]Запуск веб-сервера...[/blue]")
    console.print("Открой в браузере: [bold]http://127.0.0.1:8000[/bold]\n")

    uvicorn.run(
        "web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info",
    )


async def run_cli():
    """Запускает CLI-интерфейс."""
    from core.config import config
    from core.database import init_db
    from core.logger import get_logger
    from exchanges.gate import GateExchange
    from ui.cli import run

    logger = get_logger(__name__)

    try:
        config.validate()
    except EnvironmentError as e:
        console.print(f"\n[red]{e}[/red]\n")
        return

    init_db()
    exchange = GateExchange()

    try:
        ticker = await exchange.get_ticker("BTC/USDT", market_type="spot")
        logger.info(f"Gate.io подключён | BTC/USDT: {ticker['last']:,.2f}$")
    except Exception as e:
        console.print(f"\n[red]Ошибка подключения к Gate.io: {e}[/red]\n")
        await exchange.close()
        return

    try:
        await run(exchange)
    finally:
        await exchange.close()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "web"

    if mode == "web":
        run_web()
    elif mode == "cli":
        asyncio.run(run_cli())
    else:
        console.print(f"[red]Неизвестный режим: {mode}[/red]")
        console.print("Использование: python main.py [web|cli]")
        sys.exit(1)


if __name__ == "__main__":
    main()
