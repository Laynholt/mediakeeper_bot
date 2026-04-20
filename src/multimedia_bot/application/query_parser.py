from multimedia_bot.application.text import normalize_text
from multimedia_bot.domain.models import ParsedInlineQuery, QueryCategory


PREFIX_TO_CATEGORY = {
    "audio": QueryCategory.AUDIO,
    "image": QueryCategory.IMAGE,
    "video": QueryCategory.VIDEO,
    "voice": QueryCategory.VOICE,
    "gif": QueryCategory.GIF,
    "text": QueryCategory.TEXT,
}


def parse_inline_query(raw_query: str) -> ParsedInlineQuery:
    normalized = normalize_text(raw_query)
    if not normalized:
        return ParsedInlineQuery(raw_query=raw_query, category=QueryCategory.NONE, search_text="")

    parts = normalized.split(" ", 1)
    prefix = parts[0]
    if prefix in PREFIX_TO_CATEGORY:
        search_text = parts[1] if len(parts) > 1 else ""
        return ParsedInlineQuery(
            raw_query=raw_query,
            category=PREFIX_TO_CATEGORY[prefix],
            search_text=search_text,
        )

    return ParsedInlineQuery(
        raw_query=raw_query,
        category=QueryCategory.ALL,
        search_text=normalized,
    )
