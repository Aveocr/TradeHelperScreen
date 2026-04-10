"""
CLI-интерфейс AI Trading Assistant.
Построен на Rich — цветной, интерактивный, запускается в терминале.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable, Awaitable

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich import box

from core.config import config
from core.database import get_today_stats, is_session_blocked
from core.logger import get_logger

console = Console()
logger = get_logger(__name__)


# ─────────────────────────────────────────────
# Хелперы
# ─────────────────────────────────────────────

def clear() -> None:
    console.clear()


def header() -> Panel:
    now = datetime.now().strftime("%d.%m.%Y  %H:%M:%S")
    title = Text("AI Trading Assistant", style="bold white on blue", justify="center")
    sub = Text(f"Gate.io  |  {now}", style="dim", justify="center")
    return Panel(
        Text.assemble(title, "\n", sub),
        box=box.DOUBLE_EDGE,
        border_style="blue",
        padding=(0, 2),
    )


def risk_panel() -> Panel:
    stats = get_today_stats()
    pnl = stats["realized_pnl"]
    limit = config.DAILY_DRAWDOWN_LIMIT
    remaining = limit + pnl  # сколько ещё можно потерять

    pnl_color = "green" if pnl >= 0 else "red"
    rem_color = "green" if remaining > 2 else ("yellow" if remaining > 0 else "red")
    blocked = stats["session_blocked"]

    # Прогресс-бар просадки
    used_pct = min(abs(pnl) / limit, 1.0) if pnl < 0 else 0.0
    bar_len = 20
    filled = int(bar_len * used_pct)
    bar_color = "red" if used_pct > 0.7 else ("yellow" if used_pct > 0.4 else "green")
    bar = f"[{bar_color}]{'█' * filled}{'░' * (bar_len - filled)}[/{bar_color}]"

    status_str = (
        "[bold red]🔒 ЗАБЛОКИРОВАНА[/bold red]"
        if blocked
        else "[bold green]✓ АКТИВНА[/bold green]"
    )

    content = (
        f"  Сессия:        {status_str}\n"
        f"  P&L сегодня:   [{pnl_color}]{pnl:+.2f}$[/{pnl_color}]\n"
        f"  Лимит:         -{limit:.2f}$\n"
        f"  Осталось:      [{rem_color}]{remaining:.2f}$[/{rem_color}]\n"
        f"  Просадка:      {bar} {used_pct*100:.0f}%\n"
        f"  Сделок:        {stats['trades_count']}  "
        f"(убыточных: {stats['losses_count']})"
    )

    return Panel(
        content,
        title="[bold cyan]Риск-менеджмент[/bold cyan]",
        box=box.ROUNDED,
        border_style="cyan",
        padding=(0, 1),
    )


def rules_panel() -> Panel:
    content = (
        f"  Размер входа:  [bold]{config.ENTRY_SIZE:.0f}$[/bold]\n"
        f"  Макс. убыток:  [bold red]{config.MAX_LOSS_PER_TRADE:.0f}$ (SL = 10%)[/bold red]\n"
        f"  Мин. R:R:      [bold green]{config.MIN_RR_RATIO:.0f}:1[/bold green]  "
        f"(TP1 = {config.ENTRY_SIZE * config.MIN_RR_RATIO / 10:.0f}$ прибыли)\n"
        f"  TP1:           +{config.MAX_LOSS_PER_TRADE * 3:.0f}$  "
        f"TP2: +{config.MAX_LOSS_PER_TRADE * 5:.0f}$  "
        f"TP3: +{config.MAX_LOSS_PER_TRADE * 8:.0f}$\n"
        f"  Дневной лимит: [bold red]-{config.DAILY_DRAWDOWN_LIMIT:.0f}$[/bold red]  "
        f"({int(config.DAILY_DRAWDOWN_LIMIT / config.MAX_LOSS_PER_TRADE)} стоп-лосса max)"
    )
    return Panel(
        content,
        title="[bold magenta]Правила входа[/bold magenta]",
        box=box.ROUNDED,
        border_style="magenta",
        padding=(0, 1),
    )


def menu_panel(blocked: bool) -> Panel:
    items = [
        ("[1]", "Скрининг рынка",        "Поиск торговых возможностей"),
        ("[2]", "Анализ символа",         "TA + стакан по конкретной паре"),
        ("[3]", "Рекомендация агента",    "Claude анализирует и даёт сигнал"),
        ("[4]", "Пре-сессионный чек",     "Эмоциональное состояние + совет"),
        ("[5]", "История рекомендаций",   "Последние сигналы агента"),
        ("[6]", "Дневная статистика",     "P&L, просадка, сделки"),
        ("[7]", "Настройки",             "API ключи, параметры риска"),
        ("[Q]", "Выход",                  ""),
    ]

    rows: list[str] = []
    for key, label, desc in items:
        key_style = "[bold yellow]" if key != "[Q]" else "[bold red]"
        disabled = " [dim](сессия заблокирована)[/dim]" if blocked and key in ("[1]", "[2]", "[3]") else ""
        rows.append(
            f"  {key_style}{key}[/{'bold yellow' if key != '[Q]' else 'bold red'}]  "
            f"[white]{label}[/white]  [dim]{desc}{disabled}[/dim]"
        )

    return Panel(
        "\n".join(rows),
        title="[bold white]Меню[/bold white]",
        box=box.ROUNDED,
        border_style="white",
        padding=(0, 1),
    )


# ─────────────────────────────────────────────
# Экраны
# ─────────────────────────────────────────────

async def screen_symbol_analysis(exchange) -> None:
    """Экран: ввод символа → анализ стакана + тикер."""
    from data.market_data import MarketDataService
    from data.orderbook import OrderBookAnalyzer

    clear()
    console.print(header())
    console.print(Panel("[bold]Анализ символа[/bold]", border_style="cyan"))

    symbol = Prompt.ask(
        "  Введи символ",
        default="BTC/USDT",
    ).upper().replace(" ", "")

    market_type = Prompt.ask(
        "  Рынок",
        choices=["spot", "futures"],
        default="spot",
    )

    timeframe = Prompt.ask(
        "  Таймфрейм",
        choices=["1m", "5m", "15m", "1h", "4h"],
        default="5m",
    )

    console.print(f"\n  Загружаю данные для [bold]{symbol}[/bold]...\n")

    svc = MarketDataService(exchange)
    analyzer = OrderBookAnalyzer(exchange)

    try:
        ticker, ob_analysis = await asyncio.gather(
            svc.get_ticker(symbol, market_type),
            analyzer.analyze(symbol, depth=20, market_type=market_type),
            return_exceptions=True,
        )

        if isinstance(ticker, Exception):
            console.print(f"[red]Ошибка тикера: {ticker}[/red]")
            ticker = None
        if isinstance(ob_analysis, Exception):
            console.print(f"[red]Ошибка стакана: {ob_analysis}[/red]")
            ob_analysis = None

        # Тикер
        if ticker:
            chg_color = "green" if (ticker.get("change_24h_pct") or 0) >= 0 else "red"
            t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            t.add_column("", style="dim")
            t.add_column("", justify="right")
            t.add_row("Последняя цена", f"[bold]{ticker['last']:,.6g}$[/bold]")
            t.add_row("Bid / Ask", f"{ticker['bid']:,.6g}  /  {ticker['ask']:,.6g}")
            t.add_row("Изм. 24ч", f"[{chg_color}]{ticker.get('change_24h_pct', 0):+.2f}%[/{chg_color}]")
            t.add_row("Объём 24ч (quote)", f"{ticker.get('quote_vol_24h', 0):,.0f}$")
            t.add_row("Max 24ч", f"{ticker.get('high_24h', 0):,.6g}$")
            t.add_row("Min 24ч", f"{ticker.get('low_24h', 0):,.6g}$")
            console.print(Panel(t, title=f"[bold]{symbol}  {market_type.upper()}[/bold]", border_style="yellow"))

        # Стакан
        if ob_analysis:
            pressure_color = {
                "buy": "green", "sell": "red", "neutral": "yellow"
            }[ob_analysis["pressure"]]

            liq_status = (
                "[green]✓ Ликвидно[/green]"
                if ob_analysis["is_liquid"]
                else "[red]✗ Неликвидно[/red]"
            )

            ob_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
            ob_table.add_column("", style="dim")
            ob_table.add_column("", justify="right")
            ob_table.add_row("Статус", liq_status)
            ob_table.add_row("Спред", f"{ob_analysis['spread_pct']}%  (порог: {OrderBookAnalyzer.MAX_SPREAD_PCT}%)")
            ob_table.add_row(
                "Давление",
                f"[{pressure_color}]{ob_analysis['pressure'].upper()}[/{pressure_color}]"
                f"  (ratio: {ob_analysis['pressure_ratio']})",
            )
            ob_table.add_row("Объём BID", f"{ob_analysis['bid_volume']:,.2f}")
            ob_table.add_row("Объём ASK", f"{ob_analysis['ask_volume']:,.2f}")

            console.print(Panel(ob_table, title="[bold]Анализ стакана[/bold]", border_style="blue"))

            # Уровни поддержки/сопротивления
            if ob_analysis["support_levels"] or ob_analysis["resistance_levels"]:
                lvl_table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
                lvl_table.add_column("Тип", style="dim")
                lvl_table.add_column("Цена", justify="right")
                lvl_table.add_column("Объём", justify="right")
                lvl_table.add_column("Доля", justify="right")

                for lvl in ob_analysis["resistance_levels"]:
                    lvl_table.add_row(
                        "[red]Сопротивление[/red]",
                        str(lvl["price"]),
                        str(lvl["size"]),
                        f"{lvl['volume_pct']}%",
                    )
                for lvl in ob_analysis["support_levels"]:
                    lvl_table.add_row(
                        "[green]Поддержка[/green]",
                        str(lvl["price"]),
                        str(lvl["size"]),
                        f"{lvl['volume_pct']}%",
                    )
                console.print(Panel(lvl_table, title="[bold]Ключевые уровни (стакан)[/bold]", border_style="magenta"))

    except Exception as e:
        console.print(f"[red]Ошибка: {e}[/red]")
        logger.exception(f"Ошибка анализа {symbol}")

    console.print()
    Prompt.ask("  [dim]Нажми Enter чтобы вернуться в меню[/dim]", default="")


async def screen_screener(exchange) -> None:
    """Экран: скрининг топ монет по объёму."""
    from data.market_data import MarketDataService

    clear()
    console.print(header())
    console.print(Panel("[bold]Скрининг рынка[/bold] — топ монеты по объёму 24ч", border_style="cyan"))

    market_type = Prompt.ask(
        "  Рынок",
        choices=["spot", "futures"],
        default="spot",
    )
    top_n = IntPrompt.ask("  Сколько монет показать", default=15)

    console.print(f"\n  Загружаю тикеры Gate.io ({market_type})...\n")

    svc = MarketDataService(exchange)
    try:
        leaders = await svc.scan_volume_leaders(
            market_type=market_type,
            top_n=top_n,
            min_quote_volume=500_000,
        )

        table = Table(
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Символ", min_width=12)
        table.add_column("Цена", justify="right")
        table.add_column("Изм. 24ч", justify="right")
        table.add_column("Объём 24ч", justify="right")
        table.add_column("Спред-оценка", justify="center")

        for i, t in enumerate(leaders, 1):
            chg = t.get("change_24h_pct") or 0
            chg_str = f"[{'green' if chg >= 0 else 'red'}]{chg:+.2f}%[/{'green' if chg >= 0 else 'red'}]"
            vol = t.get("quote_vol_24h") or 0
            vol_str = f"{vol/1_000_000:.1f}M$" if vol >= 1_000_000 else f"{vol/1_000:.0f}K$"

            table.add_row(
                str(i),
                f"[bold]{t['symbol']}[/bold]",
                f"{t['last']:,.6g}",
                chg_str,
                vol_str,
                "—",  # спред будет в анализе символа
            )

        console.print(table)
        console.print(f"\n  [dim]Для детального анализа выбери [2] Анализ символа из меню.[/dim]")

    except Exception as e:
        console.print(f"[red]Ошибка скринера: {e}[/red]")
        logger.exception("Ошибка скринера")

    console.print()
    Prompt.ask("  [dim]Нажми Enter чтобы вернуться в меню[/dim]", default="")


async def screen_daily_stats() -> None:
    """Экран: подробная дневная статистика."""
    clear()
    console.print(header())

    stats = get_today_stats()
    pnl = stats["realized_pnl"]
    limit = config.DAILY_DRAWDOWN_LIMIT

    pnl_color = "green" if pnl >= 0 else "red"

    table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    table.add_column("Параметр", style="dim", min_width=22)
    table.add_column("Значение", justify="right")

    table.add_row("Дата", stats["trade_date"])
    table.add_row("P&L за день", f"[bold {pnl_color}]{pnl:+.2f}$[/bold {pnl_color}]")
    table.add_row("Лимит просадки", f"[red]-{limit:.2f}$[/red]")
    table.add_row("Осталось", f"{limit + pnl:.2f}$")
    table.add_row("Всего сделок", str(stats["trades_count"]))
    table.add_row("Убыточных", str(stats["losses_count"]))
    table.add_row(
        "Статус сессии",
        "[red]ЗАБЛОКИРОВАНА[/red]" if stats["session_blocked"] else "[green]АКТИВНА[/green]",
    )

    console.print(Panel(table, title="[bold]Дневная статистика[/bold]", border_style="cyan"))

    # Правила риска
    console.print(rules_panel())

    console.print()
    Prompt.ask("  [dim]Нажми Enter чтобы вернуться в меню[/dim]", default="")


async def screen_pre_session() -> None:
    """Экран: пре-сессионный чек (заглушка, Claude подключится в Этапе 5)."""
    clear()
    console.print(header())
    console.print(Panel(
        "[bold]Пре-сессионный чек[/bold]\n"
        "[dim]Оценка эмоционального состояния перед торгами[/dim]",
        border_style="magenta",
    ))

    console.print("\n  Ответь на несколько вопросов перед началом сессии:\n")

    score = IntPrompt.ask(
        "  Как ты оцениваешь своё эмоциональное состояние сейчас? (1 = плохо, 10 = отлично)",
        default=7,
    )

    notes = Prompt.ask(
        "  Есть что добавить? (нажми Enter чтобы пропустить)",
        default="",
    )

    # Базовая логика (без Claude — Этап 5 подключит API)
    console.print()
    if score >= 8:
        verdict = "[green]Отличное состояние![/green] Торговать можно. Придерживайся плана."
        allowed = True
    elif score >= 6:
        verdict = "[yellow]Нормальное состояние.[/yellow] Торгуй осторожно, не торопись."
        allowed = True
    elif score >= 4:
        verdict = "[yellow]Состояние ниже нормы.[/yellow] Рекомендуется сократить размер сделок вдвое."
        allowed = True
    else:
        verdict = "[red]Плохое состояние.[/red] Торговля не рекомендована. Риск импульсивных решений высок."
        allowed = False

    advice_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    advice_table.add_column("", style="dim")
    advice_table.add_column("")
    advice_table.add_row("Твоя оценка", f"[bold]{score}/10[/bold]")
    advice_table.add_row("Вердикт", verdict)
    advice_table.add_row("Торговать", "[green]ДА[/green]" if allowed else "[red]НЕТ[/red]")

    console.print(Panel(advice_table, title="[bold]Результат чека[/bold]", border_style="magenta"))

    console.print(
        "\n  [dim italic]В Этапе 5 этот чек будет дополнен анализом Claude "
        "с персональными рекомендациями.[/dim italic]\n"
    )
    Prompt.ask("  [dim]Нажми Enter чтобы вернуться в меню[/dim]", default="")


async def screen_placeholder(title: str) -> None:
    """Заглушка для ещё не реализованных экранов."""
    clear()
    console.print(header())
    console.print(Panel(
        f"[bold]{title}[/bold]\n\n"
        "[yellow]Этот раздел будет реализован в следующих этапах разработки.[/yellow]",
        border_style="yellow",
    ))
    console.print()
    Prompt.ask("  [dim]Нажми Enter чтобы вернуться в меню[/dim]", default="")


# ─────────────────────────────────────────────
# Главный цикл
# ─────────────────────────────────────────────

async def run(exchange) -> None:
    """Главный цикл CLI."""
    while True:
        clear()
        blocked = is_session_blocked()

        console.print(header())

        # Два блока рядом: риск + правила
        console.print(Columns([risk_panel(), rules_panel()], equal=True, expand=True))

        # Меню
        console.print(menu_panel(blocked))

        choice = Prompt.ask(
            "  Выбор",
            choices=["1", "2", "3", "4", "5", "6", "7", "q", "Q"],
            show_choices=False,
        ).lower()

        if choice == "q":
            console.print("\n[dim]До свидания![/dim]\n")
            break

        elif choice == "1":
            if blocked:
                console.print("[red]Сессия заблокирована. Скрининг недоступен.[/red]")
                await asyncio.sleep(1.5)
            else:
                await screen_screener(exchange)

        elif choice == "2":
            if blocked:
                console.print("[red]Сессия заблокирована.[/red]")
                await asyncio.sleep(1.5)
            else:
                await screen_symbol_analysis(exchange)

        elif choice == "3":
            if blocked:
                console.print("[red]Сессия заблокирована.[/red]")
                await asyncio.sleep(1.5)
            else:
                await screen_placeholder("Рекомендация агента (Этап 5 — Claude API)")

        elif choice == "4":
            await screen_pre_session()

        elif choice == "5":
            await screen_placeholder("История рекомендаций (Этап 5)")

        elif choice == "6":
            await screen_daily_stats()

        elif choice == "7":
            await screen_placeholder("Настройки")
