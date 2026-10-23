"""Unit tests for program field boundary values.

Feature: coaching-programs — EXAMPLE criteria for the Requirement 2 price field
that the field-validation property test (Property 2) does not pin down with the
exact boundary values:

* The inclusive price boundaries ``0.00`` and ``999999.99`` are accepted and
  normalized to scale 2 (Requirements 2.4 lower/upper bound, 2.5).
* A price carrying more than 2 fractional digits is rejected (Requirement 2.4).
* An out-of-range price — negative or strictly greater than ``999999.99`` — is
  rejected (Requirement 2.4).
* A malformed price (a value that is not a number) or an omitted price is
  rejected (Requirement 2.4).

Every invalid-input case surfaces as a Pydantic ``ValidationError`` at model
construction, which the route boundary turns into HTTP 422; no validated request
model — and therefore no ``ProgramRecord`` — is ever produced.

``ProgramCreateRequest`` and ``ProgramUpdateRequest`` (its subclass) carry
identical field constraints, so each case is asserted against both, covering the
create path (Requirement 2) and the owner-update path (Requirement 4.9).

Validates: Requirements 2.4, 2.5
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.program import ProgramCreateRequest, ProgramUpdateRequest

# Both request models share the Requirement 2 field constraints (update
# subclasses create), so every case must hold for both.
_REQUEST_MODELS = (ProgramCreateRequest, ProgramUpdateRequest)

_VALID_TITLE = "A valid program title"
_VALID_DESCRIPTION = "A valid description"


def _build_each(**fields):
    """Construct both request models with the given fields, yielding each model."""
    for model in _REQUEST_MODELS:
        yield model(**fields)


def _assert_rejected(**fields) -> None:
    """Both request models must reject the given fields with a ValidationError.

    A raised ``ValidationError`` means no validated request model is produced, so
    the service can never build a ``ProgramRecord`` — i.e. the invalid request is
    rejected without storing.
    """
    for model in _REQUEST_MODELS:
        with pytest.raises(ValidationError):
            model(**fields)


# ──────────────────────────────────────────────────────────────────────────────
# Accepted boundary prices (Requirements 2.4 bounds, 2.5 scale)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "price_input",
    [
        Decimal("0.00"),
        "0.00",
        0,
        Decimal("999999.99"),
        "999999.99",
    ],
    ids=["min-decimal", "min-str", "min-int", "max-decimal", "max-str"],
)
def test_boundary_prices_are_accepted_and_scaled(price_input):
    """The inclusive price boundaries 0.00 and 999999.99 are accepted and the
    stored price is normalized to exactly 2 fractional digits.

    Validates: Requirements 2.4, 2.5
    """
    for req in _build_each(
        title=_VALID_TITLE, description=_VALID_DESCRIPTION, price=price_input
    ):
        # Normalized to scale 2 regardless of how the input was supplied.
        assert req.price == Decimal(price_input)
        assert -req.price.as_tuple().exponent == 2


def test_min_boundary_value_is_exactly_zero():
    """The accepted lower boundary is exactly 0.00 (not merely near zero)."""
    for req in _build_each(
        title=_VALID_TITLE, description=_VALID_DESCRIPTION, price=Decimal("0.00")
    ):
        assert req.price == Decimal("0.00")


def test_max_boundary_value_is_exactly_max():
    """The accepted upper boundary is exactly 999999.99."""
    for req in _build_each(
        title=_VALID_TITLE,
        description=_VALID_DESCRIPTION,
        price=Decimal("999999.99"),
    ):
        assert req.price == Decimal("999999.99")


# ──────────────────────────────────────────────────────────────────────────────
# Prices with more than 2 fractional digits (Requirement 2.4)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "price_input",
    [
        Decimal("1.234"),
        Decimal("0.001"),
        Decimal("49.999"),
        "10.555",
        Decimal("999999.991"),
    ],
    ids=["3-digits", "tiny-3-digits", "round-up-3-digits", "str-3-digits", "near-max-3-digits"],
)
def test_price_with_more_than_two_fractional_digits_is_rejected(price_input):
    """A price carrying more than 2 fractional digits is rejected for both models.

    Validates: Requirements 2.4
    """
    _assert_rejected(
        title=_VALID_TITLE, description=_VALID_DESCRIPTION, price=price_input
    )


# ──────────────────────────────────────────────────────────────────────────────
# Out-of-range prices (Requirement 2.4)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "price_input",
    [
        Decimal("-0.01"),
        Decimal("-1.00"),
        Decimal("-999999.99"),
        "1000000.00",
        Decimal("1000000.00"),
        Decimal("9999999.99"),
    ],
    ids=["just-below-min", "negative-one", "large-negative", "str-just-over-max", "just-over-max", "far-over-max"],
)
def test_out_of_range_price_is_rejected(price_input):
    """A price that is negative or greater than 999999.99 is rejected for both
    models.

    Validates: Requirements 2.4
    """
    _assert_rejected(
        title=_VALID_TITLE, description=_VALID_DESCRIPTION, price=price_input
    )


# ──────────────────────────────────────────────────────────────────────────────
# Malformed / missing price (Requirement 2.4)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "price_input",
    [
        "not-a-number",
        "abc",
        "",
        "12.3.4",
        None,
        [49.99],
        {"amount": 49.99},
    ],
    ids=["word", "letters", "empty-str", "two-dots", "none", "list", "dict"],
)
def test_malformed_price_is_rejected(price_input):
    """A price that is not a parseable number is rejected for both models.

    Validates: Requirements 2.4
    """
    _assert_rejected(
        title=_VALID_TITLE, description=_VALID_DESCRIPTION, price=price_input
    )


def test_missing_price_is_rejected():
    """Omitting the required price field is rejected for both models.

    Validates: Requirements 2.4
    """
    for model in _REQUEST_MODELS:
        with pytest.raises(ValidationError):
            model(title=_VALID_TITLE, description=_VALID_DESCRIPTION)
