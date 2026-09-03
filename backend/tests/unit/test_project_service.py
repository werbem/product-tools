"""Unit tests for ProjectService."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.exceptions import ProjectNotFoundError
from app.application.services.project_service import ProjectService
from app.infrastructure.persistence.copilot.stores import (
    ConversationStore,
    MessageStore,
    ProjectStore,
)


@pytest.fixture
def project_service(tmp_path: Path, monkeypatch) -> ProjectService:
    persistence = tmp_path / "persistence"
    persistence.mkdir()
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.stores.DATA_DIR",
        persistence,
    )
    return ProjectService(
        store=ProjectStore(),
        conversation_store=ConversationStore(),
        message_store=MessageStore(),
    )


class TestProjectService:
    def test_create_and_get_project(self, project_service: ProjectService) -> None:
        project = project_service.create_project("测试项目", "product_improvement")
        assert project.id
        assert project.title == "测试项目"

        loaded = project_service.get_project(project.id)
        assert loaded.id == project.id

    def test_get_missing_project_raises(self, project_service: ProjectService) -> None:
        with pytest.raises(ProjectNotFoundError):
            project_service.get_project("missing-id")

    def test_list_projects(self, project_service: ProjectService) -> None:
        project_service.create_project("A")
        project_service.create_project("B")
        projects = project_service.list_projects()
        assert len(projects) == 2
