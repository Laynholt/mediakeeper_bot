from multimedia_bot.bot.handlers import _build_start_text


def test_start_text_for_admin_contains_admin_commands() -> None:
    text = _build_start_text(is_admin=True)

    assert "<b>Панель администратора</b>" in text
    assert "/admin_media" in text
    assert "/admin_cleanup_orphans" in text
    assert "<b>Отправить материал</b>" not in text


def test_start_text_for_user_does_not_expose_admin_commands() -> None:
    text = _build_start_text(is_admin=False)

    assert "<b>Отправить материал</b>" in text
    assert "<b>Что дальше</b>" in text
    assert "/admin_media" not in text
    assert "/admin_cleanup_orphans" not in text
