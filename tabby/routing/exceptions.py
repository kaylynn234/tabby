from typing import Any

from discord import Enum
from pydantic import ValidationError


class RouteError(Exception):
    """The base exception class for errors within the routing framework."""

    message: str
    """The displayed error message.

    This text should only be used for the sake of error reporting, and should not be inspected when determining the
    cause of an error.
    """

    def __init__(self, *, message: str) -> None:
        super().__init__(message)

        self.message = message


class InvalidHandlerReason(Enum):
    """The reason a handler was invalid."""

    missing_annotation = 0
    invalid_annotation = 1
    variadic_parameter = 2
    missing_parameters = 3


class InvalidHandler(RouteError):
    """A handler function was invalid."""

    reason: InvalidHandlerReason
    """The reason the handler was rejected."""

    def __init__(self, *, reason: InvalidHandlerReason, message: str) -> None:
        super().__init__(message=message)

        self.reason = reason
        self.args += reason,


class HandlerError(RouteError):
    """Executing the body of a route handler failed."""

    original: Exception
    """The original exception raised during route handling."""

    def __init__(self, *, original: Exception, message: str) -> None:
        super().__init__(message=message)

        self.original = original
        self.args += original,


class ExtractorError(HandlerError):
    """One of the route's extractors failed to run."""

    extractor: Any
    """The extractor that failed."""

    def __init__(self, *, extractor: Any, original: Exception, message: str) -> None:
        super().__init__(original=original, message=message)

        self.extractor = extractor
        self.args += extractor,


class ErrorPart(Enum):
    query_parameters = 0
    path_parameters = 1
    request_body = 2

    def message(self) -> str:
        if self is ErrorPart.path_parameters:
            return "invalid path parameters"
        elif self is ErrorPart.query_parameters:
            return "invalid query parameters"
        else:
            return "invalid request body"


class RequestValidationError(HandlerError):
    """Part of the request was invalid."""

    part: ErrorPart
    """The part of the request that caused the error"""

    def __init__(
        self,
        *,
        part: ErrorPart,
        original: Exception,
        message: str | None = None,
    ) -> None:
        super().__init__(
            original=original,
            message=message or part.message(),
        )

        self.part = part
        self.args += part,

