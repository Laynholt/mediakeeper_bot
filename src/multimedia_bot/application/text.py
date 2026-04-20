import re


def normalize_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return normalized
