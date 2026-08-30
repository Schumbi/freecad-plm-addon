class PLMError(Exception):
    """Base exception for FreeCAD-PLM addon errors."""


class APIError(PLMError):
    def __init__(self, status, message, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class AuthenticationError(APIError):
    pass


class PermissionDeniedError(APIError):
    pass


class NotFoundError(APIError):
    pass


class ConflictError(APIError):
    pass


class WorkspaceError(PLMError):
    pass


class HashMismatchError(WorkspaceError):
    pass


class EmptyGeometryError(WorkspaceError):
    pass
