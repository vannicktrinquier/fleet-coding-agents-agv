"""Domain errors. ``app.main`` turns them into JSON error responses."""


class LibraryError(Exception):
    """Base class for errors the API reports to the client."""

    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(LibraryError):
    status_code = 404


class Conflict(LibraryError):
    status_code = 409


class Unauthorized(LibraryError):
    status_code = 401
