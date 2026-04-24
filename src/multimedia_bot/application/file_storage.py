from __future__ import annotations

from pathlib import Path


def delete_local_file(path: str | None) -> bool:
    if not path:
        return False
    file_path = Path(path)
    if not file_path.exists():
        return False
    try:
        file_path.unlink()
    except OSError:
        return False
    return True
