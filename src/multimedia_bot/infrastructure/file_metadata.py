from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from PIL import Image


def infer_file_metadata(path: Path) -> dict[str, object | None]:
    mime_type, _ = mimetypes.guess_type(path.name)
    width = None
    height = None
    if mime_type and mime_type.startswith("image/"):
        with Image.open(path) as image:
            width, height = image.size

    return {
        "title": path.stem.replace("_", " ").replace("-", " ").strip() or path.stem,
        "mime_type": mime_type,
        "width": width,
        "height": height,
    }


def parse_caption_metadata(caption: str) -> dict[str, object]:
    lines = [line.strip() for line in caption.splitlines() if line.strip()]
    tags = sorted({tag.casefold() for tag in re.findall(r"(?<!\w)#([\w-]+)", caption, flags=re.UNICODE)})
    non_tag_lines = [line for line in lines if not line.startswith("#")]
    title = non_tag_lines[0] if non_tag_lines else None
    description_lines = non_tag_lines[1:] if len(non_tag_lines) > 1 else []
    description = "\n".join(description_lines) if description_lines else None
    return {
        "title": title,
        "description": description,
        "tags": tags,
    }


def parse_text_metadata(text: str) -> dict[str, object]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    tags = sorted({tag.casefold() for tag in re.findall(r"(?<!\w)#([\w-]+)", text, flags=re.UNICODE)})
    non_tag_lines = [line for line in lines if not line.startswith("#")]
    content = "\n".join(non_tag_lines).strip() or None
    title = non_tag_lines[0] if non_tag_lines else None
    description_lines = non_tag_lines[1:] if len(non_tag_lines) > 1 else []
    description = "\n".join(description_lines) if description_lines else None
    return {
        "title": title,
        "description": description,
        "tags": tags,
        "content": content,
    }
