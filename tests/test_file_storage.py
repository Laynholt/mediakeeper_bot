from pathlib import Path

from multimedia_bot.application.file_storage import delete_local_file


def test_delete_local_file_reports_whether_file_was_removed(tmp_path: Path) -> None:
    path = tmp_path / "media.mp3"
    path.write_bytes(b"media")

    assert delete_local_file(str(path)) is True
    assert not path.exists()
    assert delete_local_file(str(path)) is False
    assert delete_local_file(None) is False
