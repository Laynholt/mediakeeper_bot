from pathlib import Path

from multimedia_bot.bot.handlers import _build_import_document_path, _build_start_text


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


def test_admin_import_document_path_sanitizes_telegram_file_name(tmp_path: Path) -> None:
    import_dir = tmp_path / "imports"

    destination = _build_import_document_path("..\\nested/manifest.json", import_dir=import_dir)

    assert destination.parent == import_dir
    assert destination.name.endswith(".json")
    assert "manifest" in destination.name
    assert destination != import_dir / "manifest.json"


def test_admin_import_document_path_keeps_zip_suffix(tmp_path: Path) -> None:
    import_dir = tmp_path / "imports"

    destination = _build_import_document_path("backup.zip", import_dir=import_dir)

    assert destination.parent == import_dir
    assert destination.name.endswith(".zip")
