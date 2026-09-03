"""Application-layer exceptions."""


class AppError(Exception):
    pass


class ProjectNotFoundError(AppError):
    pass


class ConversationNotFoundError(AppError):
    pass


class ArtifactNotFoundError(AppError):
    pass


class ProjectArchivedError(AppError):
    pass


class ConversationProjectMismatchError(AppError):
    pass


class KnowledgeNoteNotFoundError(AppError):
    pass
