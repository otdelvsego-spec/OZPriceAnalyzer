from __future__ import annotations

import re
from collections.abc import Iterable


GROUP_PREFIXES = ("бргс", "гс", "бант")


def article_group_rank(article: str) -> int:
    normalized = article.strip().casefold()
    for index, prefix in enumerate(GROUP_PREFIXES):
        if normalized.startswith(prefix):
            return index
    return len(GROUP_PREFIXES)


def natural_article_key(article: str) -> tuple[tuple[int, object], ...]:
    compact = re.sub(r"\s+", "", article.strip().casefold().replace("ё", "е"))
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", compact)
        if part
    )


def default_article_sort_key(article: str) -> tuple[int, tuple[tuple[int, object], ...]]:
    return article_group_rank(article), natural_article_key(article)


def default_article_order(articles: Iterable[str]) -> list[str]:
    return sorted(articles, key=default_article_sort_key)


def insert_at_group_end(order: list[str], article: str) -> list[str]:
    result = [value for value in order if value != article]
    rank = article_group_rank(article)
    same_group = [index for index, value in enumerate(result) if article_group_rank(value) == rank]
    if same_group:
        result.insert(same_group[-1] + 1, article)
        return result
    for index, value in enumerate(result):
        if article_group_rank(value) > rank:
            result.insert(index, article)
            return result
    result.append(article)
    return result
