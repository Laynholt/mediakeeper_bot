TELEGRAM_MESSAGE_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
RECORD_TITLE_LIMIT = 255


def ensure_record_title_limit(value: str, *, field_name: str = "Алиас") -> None:
    _ensure_text_limit(value, limit=RECORD_TITLE_LIMIT, field_name=field_name)


def ensure_telegram_message_text_limit(value: str | None, *, field_name: str = "Текст") -> None:
    _ensure_text_limit(value, limit=TELEGRAM_MESSAGE_TEXT_LIMIT, field_name=field_name)


def ensure_telegram_caption_limit(value: str | None, *, field_name: str = "Подпись") -> None:
    _ensure_text_limit(value, limit=TELEGRAM_CAPTION_LIMIT, field_name=field_name)


def trim_telegram_message_text(value: str) -> str:
    return _trim_text(value, limit=TELEGRAM_MESSAGE_TEXT_LIMIT)


def trim_telegram_caption(value: str) -> str:
    return _trim_text(value, limit=TELEGRAM_CAPTION_LIMIT)


def _ensure_text_limit(value: str | None, *, limit: int, field_name: str) -> None:
    if value is None:
        return
    if len(value) > limit:
        raise ValueError(f"{field_name} слишком длинный: {len(value)} символов при лимите {limit}.")


def _trim_text(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3].rstrip() + "..."
