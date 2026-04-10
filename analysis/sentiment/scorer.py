"""
Агрегатор сентимента: объединяет Reddit + другие источники в единый скор.
Если Reddit недоступен — выводит сентимент из ТА сигнала.
"""

from __future__ import annotations

from analysis.sentiment.reddit import RedditSentiment


def from_ta_signal(ta_signal: dict) -> dict:
    """
    Строит сентимент на основе ТА сигнала (когда Reddit недоступен).

    Args:
        ta_signal: результат ta_signals.generate()

    Returns:
        словарь того же формата, что aggregate()
    """
    direction  = ta_signal.get("direction", "neutral")
    score_raw  = ta_signal.get("score", 0)        # -100 .. +100
    confidence = ta_signal.get("confidence", "low")

    # Нормализуем score до -1..+1
    norm_score = max(-1.0, min(1.0, score_raw / 100))

    label = (
        "bullish" if norm_score > 0.1 else
        "bearish" if norm_score < -0.1 else
        "neutral"
    )

    summary = (
        f"Сентимент из ТА (Reddit недоступен): сигнал={direction.upper()}, "
        f"скор={score_raw:+d}/100, уверенность={confidence}."
    )

    return {
        "score":      round(norm_score, 3),
        "label":      label,
        "confidence": confidence,
        "summary":    summary,
        "sources": {
            "reddit": {
                "score":         0,
                "label":         "unknown",
                "total_posts":   0,
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "top_titles":    [],
                "error":         "Reddit недоступен — используется ТА",
            },
            "ta_fallback": {
                "direction":  direction,
                "score":      score_raw,
                "confidence": confidence,
            },
        },
    }


def aggregate(reddit: RedditSentiment) -> dict:
    """
    Агрегирует все источники сентимента в единый результат.
    Сейчас: только Reddit. В будущем сюда добавятся новости, Twitter и т.д.

    Returns:
        {
            "score":       float,   # -1.0 .. +1.0
            "label":       str,     # bullish / bearish / neutral
            "confidence":  str,     # high / medium / low
            "summary":     str,     # текстовое описание
            "sources":     dict,    # детали по каждому источнику
        }
    """
    reddit_score = reddit.score if not reddit.error else 0.0
    reddit_posts = reddit.total_posts

    # Взвешенный итоговый скор (пока только Reddit)
    final_score = reddit_score

    # Уверенность: зависит от количества постов
    if reddit.error or reddit_posts == 0:
        confidence = "low"
    elif reddit_posts >= 15:
        confidence = "high"
    elif reddit_posts >= 5:
        confidence = "medium"
    else:
        confidence = "low"

    label = (
        "bullish" if final_score > 0.1 else
        "bearish" if final_score < -0.1 else
        "neutral"
    )

    # Текстовое резюме
    if reddit.error:
        summary = f"Данные Reddit недоступны: {reddit.error}"
    elif reddit_posts == 0:
        summary = "Упоминаний в Reddit за последние 24ч не найдено."
    else:
        bull_pct = round(reddit.bullish_count / reddit_posts * 100) if reddit_posts else 0
        bear_pct = round(reddit.bearish_count / reddit_posts * 100) if reddit_posts else 0
        summary = (
            f"Reddit: {reddit_posts} постов за 24ч — "
            f"{bull_pct}% бычьих, {bear_pct}% медвежьих. "
            f"Общий сентимент: {label.upper()}."
        )

    return {
        "score":      round(final_score, 3),
        "label":      label,
        "confidence": confidence,
        "summary":    summary,
        "sources": {
            "reddit": {
                "score":         reddit.score,
                "label":         reddit.label,
                "total_posts":   reddit.total_posts,
                "bullish_count": reddit.bullish_count,
                "bearish_count": reddit.bearish_count,
                "neutral_count": reddit.neutral_count,
                "top_titles":    reddit.top_titles,
                "error":         reddit.error,
            }
        },
    }
