"""
Reddit-парсер для сбора сентимента по криптовалютам.
Ищет упоминания тикера в топовых крипто-сабреддитах.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import praw

from core.config import config
from core.logger import get_logger

logger = get_logger(__name__)

SUBREDDITS = [
    "CryptoCurrency",
    "CryptoMarkets",
    "altcoin",
    "ethtrader",
    "Bitcoin",
    "SatoshiStreetBets",
]

# Слова, усиливающие сигнал
BULLISH_WORDS = {
    "moon", "pump", "bullish", "buy", "long", "breakout", "surge",
    "rally", "ath", "accumulate", "undervalued", "gem", "🚀", "🔥", "📈",
    "mooning", "explode", "rip", "gains",
}
BEARISH_WORDS = {
    "dump", "bearish", "sell", "short", "crash", "drop", "fall",
    "rug", "scam", "dead", "rekt", "📉", "🩸", "correction", "collapse",
    "overvalued", "exit", "capitulation",
}


@dataclass
class RedditPost:
    title:       str
    text:        str
    score:       int
    upvote_ratio: float
    num_comments: int
    created_utc:  float
    url:          str
    subreddit:    str
    sentiment:    str = "neutral"   # bullish / bearish / neutral
    weight:       float = 1.0


@dataclass
class RedditSentiment:
    symbol:       str
    posts:        list[RedditPost] = field(default_factory=list)
    total_posts:  int = 0
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    score:        float = 0.0      # -1.0 .. +1.0
    label:        str = "neutral"  # bullish / bearish / neutral
    top_titles:   list[str] = field(default_factory=list)
    error:        str = ""


def _make_client() -> praw.Reddit | None:
    """Создаёт PRAW-клиент. Возвращает None если ключи не заданы."""
    if not config.REDDIT_CLIENT_ID or not config.REDDIT_CLIENT_SECRET:
        return None
    return praw.Reddit(
        client_id     = config.REDDIT_CLIENT_ID,
        client_secret = config.REDDIT_CLIENT_SECRET,
        user_agent    = config.REDDIT_USER_AGENT,
    )


def _extract_ticker(symbol: str) -> str:
    """Извлекает базовый тикер из пары: 'BTC/USDT' → 'BTC'."""
    return symbol.split("/")[0].upper()


def _score_text(text: str) -> tuple[str, float]:
    """
    Определяет сентимент текста по ключевым словам.
    Возвращает (label, weight).
    """
    lower = text.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in lower)
    bear = sum(1 for w in BEARISH_WORDS if w in lower)

    if bull > bear:
        return "bullish", 1.0 + bull * 0.1
    if bear > bull:
        return "bearish", 1.0 + bear * 0.1
    return "neutral", 1.0


async def fetch_sentiment(symbol: str, limit_per_sub: int = 10) -> RedditSentiment:
    """
    Ищет упоминания тикера на Reddit и возвращает агрегированный сентимент.

    Args:
        symbol:         торговая пара, напр. 'BTC/USDT'
        limit_per_sub:  сколько постов брать с каждого сабреддита

    Returns:
        RedditSentiment с агрегированными данными
    """
    ticker = _extract_ticker(symbol)
    result = RedditSentiment(symbol=symbol)

    client = _make_client()
    if client is None:
        result.error = "Reddit API ключи не настроены (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET)"
        logger.warning(result.error)
        return result

    posts: list[RedditPost] = []

    for sub_name in SUBREDDITS:
        try:
            subreddit = client.subreddit(sub_name)
            # Ищем в горячем и новом
            for submission in subreddit.search(
                ticker,
                sort="new",
                time_filter="day",
                limit=limit_per_sub,
            ):
                full_text = f"{submission.title} {submission.selftext}"
                if ticker.lower() not in full_text.lower():
                    continue

                sentiment, weight = _score_text(full_text)

                # Взвешиваем по upvote score
                upvote_weight = max(1.0, submission.score / 100)
                weight *= upvote_weight

                posts.append(RedditPost(
                    title        = submission.title[:200],
                    text         = submission.selftext[:500],
                    score        = submission.score,
                    upvote_ratio = submission.upvote_ratio,
                    num_comments = submission.num_comments,
                    created_utc  = submission.created_utc,
                    url          = f"https://reddit.com{submission.permalink}",
                    subreddit    = sub_name,
                    sentiment    = sentiment,
                    weight       = weight,
                ))

        except Exception as e:
            logger.warning(f"Reddit r/{sub_name}: {e}")

    if not posts:
        result.error = f"Постов с упоминанием {ticker} за последние 24ч не найдено"
        return result

    # Агрегация
    bull_w = sum(p.weight for p in posts if p.sentiment == "bullish")
    bear_w = sum(p.weight for p in posts if p.sentiment == "bearish")
    neut_w = sum(p.weight for p in posts if p.sentiment == "neutral")
    total_w = bull_w + bear_w + neut_w or 1

    score = (bull_w - bear_w) / total_w  # -1 .. +1

    result.posts         = sorted(posts, key=lambda p: p.score, reverse=True)
    result.total_posts   = len(posts)
    result.bullish_count = sum(1 for p in posts if p.sentiment == "bullish")
    result.bearish_count = sum(1 for p in posts if p.sentiment == "bearish")
    result.neutral_count = sum(1 for p in posts if p.sentiment == "neutral")
    result.score         = round(score, 3)
    result.label         = "bullish" if score > 0.1 else "bearish" if score < -0.1 else "neutral"
    result.top_titles    = [p.title for p in result.posts[:5]]

    logger.info(
        f"Reddit {ticker}: {len(posts)} постов | "
        f"bull={result.bullish_count} bear={result.bearish_count} | "
        f"score={result.score}"
    )
    return result


def to_dict(sent: RedditSentiment) -> dict:
    return {
        "symbol":        sent.symbol,
        "total_posts":   sent.total_posts,
        "bullish_count": sent.bullish_count,
        "bearish_count": sent.bearish_count,
        "neutral_count": sent.neutral_count,
        "score":         sent.score,
        "label":         sent.label,
        "top_titles":    sent.top_titles,
        "error":         sent.error,
    }
