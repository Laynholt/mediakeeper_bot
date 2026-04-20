"""Initial schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("performer", sa.String(length=255), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_path"),
        sa.UniqueConstraint("telegram_file_id"),
    )
    op.create_index("ix_media_items_search_text", "media_items", ["search_text"], unique=False)
    op.create_index("ix_media_items_title", "media_items", ["title"], unique=False)
    op.create_index("ix_media_items_type", "media_items", ["type"], unique=False)

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_tags_slug", "tags", ["slug"], unique=True)

    op.create_table(
        "media_tags",
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["media_id"], ["media_items.id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.PrimaryKeyConstraint("media_id", "tag_id"),
    )

    op.create_table(
        "search_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("query_raw", sa.Text(), nullable=False),
        sa.Column("query_type", sa.String(length=32), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_logs_user_id", "search_logs", ["user_id"], unique=False)

    op.create_table(
        "chosen_result_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("result_id", sa.String(length=255), nullable=False),
        sa.Column("query_raw", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chosen_result_logs_user_id", "chosen_result_logs", ["user_id"], unique=False)

    op.create_table(
        "admin_media_drafts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("suggested_title", sa.String(length=255), nullable=False),
        sa.Column("awaiting_alias_input", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("performer", sa.String(length=255), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("admin_user_id"),
    )
    op.create_index("ix_admin_media_drafts_admin_user_id", "admin_media_drafts", ["admin_user_id"], unique=True)

    op.create_table(
        "user_media_submissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("submitter_user_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("suggested_title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("performer", sa.String(length=255), nullable=True),
        sa.Column("duration", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("review_chat_id", sa.Integer(), nullable=True),
        sa.Column("review_message_id", sa.Integer(), nullable=True),
        sa.Column("editing_admin_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_media_submissions_submitter_user_id",
        "user_media_submissions",
        ["submitter_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_user_media_submissions_status",
        "user_media_submissions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_user_media_submissions_editing_admin_user_id",
        "user_media_submissions",
        ["editing_admin_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_media_submissions_editing_admin_user_id",
        table_name="user_media_submissions",
    )
    op.drop_index("ix_user_media_submissions_status", table_name="user_media_submissions")
    op.drop_index(
        "ix_user_media_submissions_submitter_user_id",
        table_name="user_media_submissions",
    )
    op.drop_table("user_media_submissions")
    op.drop_index("ix_admin_media_drafts_admin_user_id", table_name="admin_media_drafts")
    op.drop_table("admin_media_drafts")
    op.drop_index("ix_chosen_result_logs_user_id", table_name="chosen_result_logs")
    op.drop_table("chosen_result_logs")
    op.drop_index("ix_search_logs_user_id", table_name="search_logs")
    op.drop_table("search_logs")
    op.drop_table("media_tags")
    op.drop_index("ix_tags_slug", table_name="tags")
    op.drop_table("tags")
    op.drop_index("ix_media_items_type", table_name="media_items")
    op.drop_index("ix_media_items_title", table_name="media_items")
    op.drop_index("ix_media_items_search_text", table_name="media_items")
    op.drop_table("media_items")
