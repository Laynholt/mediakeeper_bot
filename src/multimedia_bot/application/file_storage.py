from __future__ import annotations

from pathlib import Path


def delete_local_file(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        return
