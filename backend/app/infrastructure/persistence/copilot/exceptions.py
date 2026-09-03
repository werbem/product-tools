"""Persistence exceptions for Copilot stores."""


class PersistenceError(Exception):
    pass


class NotFoundError(PersistenceError):
    pass


class DuplicateIdError(PersistenceError):
    pass


class CorruptPersistenceError(PersistenceError):
    pass
