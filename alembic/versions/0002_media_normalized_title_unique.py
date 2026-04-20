"""Add normalized media title with uniqueness constraint.

Revision ID: 0002_media_normalized_title_unique
Revises: 0001_initial
Create Date: 2026-04-19
"""

from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa


revision = "0002_media_normalized_title_unique"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.add_column(sa.Column("normalized_title", sa.String(length=255), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, title FROM media_items")).mappings().all()

    seen_titles: dict[str, tuple[int, str]] = {}
    for row in rows:
        normalized_title = _normalize_title(row["title"])
        if not normalized_title:
            raise RuntimeError(
                f"Media item #{row['id']} has an empty normalized title and cannot be migrated safely."
            )
        duplicate = seen_titles.get(normalized_title)
        if duplicate is not None:
            raise RuntimeError(
                "Duplicate media aliases detected during migration: "
                f"#{duplicate[0]} '{duplicate[1]}' and #{row['id']} '{row['title']}'."
            )
        seen_titles[normalized_title] = (row["id"], row["title"])
        connection.execute(
            sa.text("UPDATE media_items SET normalized_title = :normalized_title WHERE id = :id"),
            {"normalized_title": normalized_title, "id": row["id"]},
        )

    with op.batch_alter_table("media_items") as batch_op:
        batch_op.alter_column("normalized_title", existing_type=sa.String(length=255), nullable=False)
        batch_op.create_index(
            "ix_media_items_normalized_title",
            ["normalized_title"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.drop_index("ix_media_items_normalized_title")
        batch_op.drop_column("normalized_title")


def _normalize_title(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())
