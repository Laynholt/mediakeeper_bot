"""Add text record support to media, drafts, and submissions.

Revision ID: 0003_text_support_and_single_admin_review
Revises: 0002_media_normalized_title_unique
Create Date: 2026-04-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0003_text_support_and_single_admin_review"
down_revision = "0002_media_normalized_title_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.add_column(sa.Column("content_text", sa.Text(), nullable=True))

    with op.batch_alter_table("admin_media_drafts") as batch_op:
        batch_op.add_column(sa.Column("content_text", sa.Text(), nullable=True))
        batch_op.alter_column(
            "storage_path",
            existing_type=sa.String(length=512),
            nullable=True,
        )

    with op.batch_alter_table("user_media_submissions") as batch_op:
        batch_op.add_column(sa.Column("content_text", sa.Text(), nullable=True))
        batch_op.alter_column(
            "storage_path",
            existing_type=sa.String(length=512),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("user_media_submissions") as batch_op:
        batch_op.alter_column(
            "storage_path",
            existing_type=sa.String(length=512),
            nullable=False,
        )
        batch_op.drop_column("content_text")

    with op.batch_alter_table("admin_media_drafts") as batch_op:
        batch_op.alter_column(
            "storage_path",
            existing_type=sa.String(length=512),
            nullable=False,
        )
        batch_op.drop_column("content_text")

    with op.batch_alter_table("media_items") as batch_op:
        batch_op.drop_column("content_text")
