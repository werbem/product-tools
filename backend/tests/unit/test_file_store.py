"""Unit tests for file_store persistence path and round-trip writes."""

from pathlib import Path

from app.config.settings import settings
from app.infrastructure.persistence import file_store


class TestDataDirOverride:
    def test_app_data_dir_override(self, tmp_path: Path) -> None:
        from app.config.settings import Settings

        s = Settings(app_data_dir=tmp_path)
        assert s.data_dir == tmp_path
        assert tmp_path.exists()

    def test_app_data_dir_empty_string_ignored(self) -> None:
        from app.config.settings import Settings

        s = Settings(app_data_dir="")
        assert s.data_dir == s.project_root / "data"


class TestDataDir:
    def test_data_dir_unified_with_settings(self) -> None:
        """DATA_DIR must point into settings.data_dir (the mounted volume),
        not a container-layer path derived from __file__."""
        assert file_store.DATA_DIR == settings.data_dir / "persistence"

    def test_data_dir_is_under_project_data(self) -> None:
        resolved = str(file_store.DATA_DIR.resolve())
        assert resolved.endswith("data/persistence")


class TestRoundTrip:
    def test_save_and_load_reports(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(file_store, "DATA_DIR", tmp_path)
        file_store.save_reports({"r1": {"status": "completed"}})
        assert file_store.load_reports() == {"r1": {"status": "completed"}}

    def test_save_and_load_tasks(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(file_store, "DATA_DIR", tmp_path)
        file_store.save_tasks({"t1": {"status": "running"}})
        assert file_store.load_tasks() == {"t1": {"status": "running"}}
