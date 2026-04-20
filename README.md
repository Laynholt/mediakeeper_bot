# Telegram Inline Media Bot MVP

Telegram inline bot on `aiogram 3` with cached media delivery via Telegram `file_id`, SQLite storage, folder-based CLI import, live admin ingestion from private messages, text entries with aliases, and user submissions with moderation.

## Features

- Inline search with `audio`, `image`, `video`, `voice`, `text`, or free-text queries.
- Empty inline query returns helper hints plus popular media.
- SQLite catalog with tags, analytics, and usage counters.
- CLI import from JSON manifest.
- Admin-only private-message ingestion without bot restart.
- Text snippets can be stored as separate catalog items and sent via inline mode.
- User submissions are forwarded to one admin in a private chat.
- Docker-based local run.

## Requirements

- Python 3.12+
- `uv`
- Telegram bot with inline mode enabled
- Dedicated Telegram storage chat where the bot can upload media and keep messages
- One Telegram user ID for the administrator who receives moderation requests in a private chat

## Quick Start

1. Copy `.env.example` to `.env` and fill in real values.
2. Install dependencies:

```bash
uv sync
```

3. Apply migrations:

```bash
uv run alembic upgrade head
```

4. Start the bot:

```bash
uv run python -m multimedia_bot
```

## Inline Usage

- `@botname`
- `@botname audio rain`
- `@botname image sunset`
- `@botname video intro`
- `@botname voice quote`
- `@botname text greeting`
- `@botname rain ambience`

## CLI Import

Example:

```bash
uv run python -m multimedia_bot.cli.import_media --manifest stuff/media/manifest.json
```

Manifest shape:

```json
{
  "items": [
    {
      "path": "audio/rain.mp3",
      "type": "audio",
      "title": "Rain Ambience",
      "description": "Soft rain loop",
      "caption": "Rain ambience",
      "tags": ["rain", "ambience"],
      "performer": "Catalog",
      "duration": 180
    },
    {
      "type": "text",
      "title": "greeting",
      "description": "Короткое приветствие",
      "content": "Привет, мир!",
      "tags": ["hello", "welcome"]
    }
  ]
}
```

Relative `path` values are resolved from the manifest directory. For `text` items `path` is not used.

The repository already contains three generated sample files in `stuff/media/audio`, `stuff/media/image`, and `stuff/media/video`, so you can smoke-test import and admin ingestion immediately.

## Live Admin Ingestion

Set `ADMIN_USER_ID` to the Telegram user ID of the single administrator.

Then the admin can send media or plain text to the bot in a private chat:

- audio message -> saved to `stuff/media/audio/`
- photo -> saved to `stuff/media/image/`
- video -> saved to `stuff/media/video/`
- voice message -> saved to `stuff/media/voice/`
- text message -> saved as a text catalog item without a local file

The bot will:

1. Download the media locally.
2. Save it as a draft that is not yet visible in inline mode. Text drafts skip file download.
3. Show inline buttons: use suggested alias, enter alias, or cancel.
4. Only after the alias is confirmed, upload media to the storage chat to obtain a Telegram `file_id`.
5. Upsert the record into SQLite and publish it for inline search.

Caption handling:

- next text message after pressing `Enter alias` -> alias/title used in inline search
- first non-empty non-hashtag caption line -> suggested title
- remaining lines -> description
- hashtags -> tags

If caption is empty, the suggested title falls back to the file name. For text entries the first non-empty line becomes the suggested alias, the remaining text is stored as content, and hashtags become tags.

## User Submission Moderation

Set `ADMIN_USER_ID` to the Telegram user ID of the admin.

Then a regular user can send `audio`, `photo`, `video`, `voice`, or plain text to the bot in a private chat. The bot will:

1. Download the media locally when needed.
2. Show inline buttons to use the suggested title, enter a custom title, or cancel.
3. Forward the prepared submission to the admin's private chat after the title is confirmed.
4. Let the admin moderate it via inline buttons: accept, reject, or edit title.
5. Publish the item into the inline catalog only after the admin accepts it.

If the admin chooses `Edit title`, the next text message from that admin becomes the final title and the submission is approved immediately.

## Docker

```bash
docker compose up --build
```

The container runs Alembic migrations and then starts polling.

## Notes

- MVP uses polling only.
- Media delivery is `file_id` only, not public URLs.
- The storage chat messages are intentionally retained.
