import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # Gate.io
    GATE_API_KEY: str = os.getenv("GATE_API_KEY", "")
    GATE_API_SECRET: str = os.getenv("GATE_API_SECRET", "")

    # Anthropic
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Reddit
    REDDIT_CLIENT_ID: str = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USER_AGENT: str = os.getenv("REDDIT_USER_AGENT", "TradingBot/1.0")

    # Telegram (опционально)
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Риск-менеджмент
    MAX_LOSS_PER_TRADE: float = float(os.getenv("MAX_LOSS_PER_TRADE", "1.0"))
    DAILY_DRAWDOWN_LIMIT: float = float(os.getenv("DAILY_DRAWDOWN_LIMIT", "6.0"))
    ENTRY_SIZE: float = float(os.getenv("ENTRY_SIZE", "10.0"))
    MIN_RR_RATIO: float = float(os.getenv("MIN_RR_RATIO", "3.0"))

    # БД
    DB_PATH: str = str(BASE_DIR / "data" / "trading.db")

    # Claude модель
    CLAUDE_MODEL: str = "claude-sonnet-4-6"

    def validate(self) -> None:
        """Проверяет, что ключевые переменные заданы."""
        missing = []
        if not self.GATE_API_KEY:
            missing.append("GATE_API_KEY")
        if not self.ANTHROPIC_API_KEY:
            missing.append("ANTHROPIC_API_KEY")
        if missing:
            raise EnvironmentError(
                f"Отсутствуют обязательные переменные окружения: {', '.join(missing)}\n"
                f"Скопируй .env.example в .env и заполни значения."
            )


config = Config()
