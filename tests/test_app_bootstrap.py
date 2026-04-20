from __future__ import annotations

from aiogram.types import BotCommandScopeAllPrivateChats, BotCommandScopeChat

from multimedia_bot.bot import app


def test_apply_migrations_uses_project_alembic_config(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_upgrade(config, revision: str) -> None:
        captured["config_path"] = config.config_file_name
        captured["revision"] = revision

    monkeypatch.setattr(app.command, "upgrade", fake_upgrade)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    app._apply_migrations("sqlite+aiosqlite:///./data/test.db")

    assert captured["revision"] == "head"
    assert captured["config_path"] == str(app._project_root() / "alembic.ini")


async def test_configure_bot_commands_uses_separate_scopes_for_single_admin() -> None:
    class FakeBot:
        def __init__(self) -> None:
            self.commands_calls: list[tuple[list[str], object]] = []
            self.short_description: str | None = None
            self.description: str | None = None

        async def set_my_commands(self, commands, scope=None):
            self.commands_calls.append(([command.command for command in commands], scope))

        async def set_my_short_description(self, text: str) -> None:
            self.short_description = text

        async def set_my_description(self, text: str) -> None:
            self.description = text

    bot = FakeBot()

    await app._configure_bot_commands(bot, 42)

    assert len(bot.commands_calls) == 2

    public_commands, public_scope = bot.commands_calls[0]
    assert public_commands == ["start"]
    assert isinstance(public_scope, BotCommandScopeAllPrivateChats)

    admin_commands, admin_scope = bot.commands_calls[1]
    assert admin_commands == [
        "start",
        "cancel",
        "admin_media",
        "admin_export",
        "admin_reimport",
        "admin_cleanup_orphans",
    ]
    assert isinstance(admin_scope, BotCommandScopeChat)
    assert admin_scope.chat_id == 42
    assert bot.short_description is not None
    assert bot.description is not None
