from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import typing

from discord import Enum
from typing_extensions import Self


class FieldErrorReason(Enum):
    invalid = "invalid"
    missing = "missing"


class ExtractionError(Exception):
    field: str | None
    """The field where extraction failed, or `None` if top-level extraction failed."""

    expected_type: type
    """The expected type of the value"""

    reason: FieldErrorReason
    """The reason that extracting the value failed."""

    def __init__(self, *, field: str | None, expected_type: type, reason: FieldErrorReason) -> None:
        super().__init__(field, expected_type, reason)

        self.field = field
        self.expected_type = expected_type
        self.reason = reason

    def __str__(self) -> str:
        field = self.field or "the value"

        if self.reason is FieldErrorReason.invalid:
            return f"couldn't convert {field} to {self.expected_type}"
        else:
            return f"{field} was missing, so it couldn't be converted to {self.expected_type}"

    def nest(self, attr: str) -> Self:
        previous_field = f"{self.field}." if self.field else ""
        field = f"{previous_field}{attr}"

        return ExtractionError(field=field, expected_type=self.expected_type, reason=self.reason)


class Extractable:
    """A mix-in class for "extracting" a strongly-typed value from untyped data."""

    @classmethod
    def extract(cls, values: Any) -> Self:
        result = {}

        if not isinstance(values, Mapping):
            raise ExtractionError(
                field=None,
                expected_type=cls,
                reason=FieldErrorReason.invalid,
            )

        for attr, expected_type in typing.get_type_hints(cls).items():
            if attr not in values:
                raise ExtractionError(
                    field=attr,
                    expected_type=expected_type,
                    reason=FieldErrorReason.missing,
                )

            field_value = values[attr]

            if issubclass(expected_type, Extractable):
                try:
                    result[attr] = expected_type.extract(field_value)
                except ExtractionError as error:
                    raise error.nest(attr) from None

                continue

            try:
                result[attr] = expected_type(field_value)
            except (ValueError, TypeError):
                raise ExtractionError(
                    field=attr,
                    expected_type=expected_type,
                    reason=FieldErrorReason.invalid,
                )

        return cls(**result)
