from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class MediaType(StrEnum):
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    TEXT = "text"


class QueryCategory(StrEnum):
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    TEXT = "text"
    ALL = "all"
    NONE = "none"


class SubmissionStatus(StrEnum):
    AWAITING_USER_CHOICE = "awaiting_user_choice"
    AWAITING_USER_TITLE = "awaiting_user_title"
    PENDING_REVIEW = "pending_review"
    AWAITING_ADMIN_TITLE = "awaiting_admin_title"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class MediaItem:
    id: int
    media_type: MediaType
    title: str
    storage_path: str | None = None
    description: str | None = None
    caption: str | None = None
    content: str | None = None
    search_text: str = ""
    telegram_file_id: str | None = None
    mime_type: str | None = None
    performer: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    tags: list[str] = field(default_factory=list)
    is_active: bool = True
    usage_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class UploadedMedia:
    file_id: str
    chat_id: int | None = None
    message_id: int | None = None


@dataclass(slots=True)
class ParsedInlineQuery:
    raw_query: str
    category: QueryCategory
    search_text: str


@dataclass(slots=True)
class SearchRequest:
    query_text: str
    category: QueryCategory
    limit: int


@dataclass(slots=True)
class IngestionMetadata:
    media_type: MediaType
    path: str | None
    title: str
    description: str | None = None
    caption: str | None = None
    content: str | None = None
    tags: list[str] = field(default_factory=list)
    performer: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None


@dataclass(slots=True)
class AdminMediaDraft:
    id: int
    admin_user_id: int
    media_type: MediaType
    path: str | None
    suggested_title: str
    awaiting_alias_input: bool = False
    description: str | None = None
    caption: str | None = None
    content: str | None = None
    tags: list[str] = field(default_factory=list)
    performer: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    created_at: datetime | None = None


@dataclass(slots=True)
class UserMediaSubmission:
    id: int
    submitter_user_id: int
    media_type: MediaType
    path: str | None
    suggested_title: str
    status: SubmissionStatus
    title: str | None = None
    description: str | None = None
    caption: str | None = None
    content: str | None = None
    tags: list[str] = field(default_factory=list)
    performer: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    mime_type: str | None = None
    review_chat_id: int | None = None
    review_message_id: int | None = None
    editing_admin_user_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
