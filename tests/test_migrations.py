from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_tables(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "migrated.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "admin_media_drafts",
        "chosen_result_logs",
        "media_items",
        "media_tags",
        "search_logs",
        "tags",
        "user_media_submissions",
    }
    media_columns = {column["name"] for column in inspector.get_columns("media_items")}
    assert "normalized_title" in media_columns
