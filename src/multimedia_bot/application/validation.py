from __future__ import annotations

import unicodedata

from multimedia_bot.application.telegram_limits import RECORD_TITLE_LIMIT
from multimedia_bot.application.text import normalize_text


def sanitize_title(value: str | None) -> str:
    if value is None:
        return ""
    visible_characters = [
        character
        for character in value
        if unicodedata.category(character)[0] != "C"
    ]
    return " ".join("".join(visible_characters).split()).strip()


def is_valid_record_title(value: str | None) -> bool:
    sanitized = sanitize_title(value)
    if not sanitized:
        return False
    if len(sanitized) > RECORD_TITLE_LIMIT:
        return False
    return any(_is_meaningful_character(character) for character in sanitized)


def normalize_record_title(value: str | None) -> str:
    sanitized = sanitize_title(value)
    if not sanitized:
        return ""
    return normalize_text(sanitized)


def _is_meaningful_character(character: str) -> bool:
    category = unicodedata.category(character)
    return category[0] in {"L", "N", "M", "S"}
