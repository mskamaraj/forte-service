"""Property-based test for program field validation.

Feature: coaching-programs, Property 2: Invalid program fields are rejected
without storing. For any program create/update request whose title, description,
or price violates a Requirement 2 field constraint, model construction raises a
Pydantic ``ValidationError`` -- the request never yields a validated model, so no
``ProgramRecord`` can be built and nothing is stored. At the route boundary this
``ValidationError`` surfaces as HTTP 422 (Requirements 2.1, 2.2, 2.3, 2.5, 2.6,
2.7) and, for the owner-update path, leaves the stored Program unchanged
(Requirement 4.9).

Because ``ProgramCreateRequest`` and ``ProgramUpdateRequest`` (its subclass)
carry identical field constraints, every invalid-input case is asserted against
both, covering the create path (Requirement 2) and the owner-update path
(Requirement 4.9) with the same generators.

Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 4.9
"""

from decimal import Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.models.program import ProgramCreateRequest, ProgramUpdateRequest

# Both request models share the Requirement 2 field constraints; a value that is
# invalid for one is invalid for the other. Asserting against both exercises the
# create path (Req 2) and the owner-update path (Req 4.9) together.
_REQUEST_MODELS = (ProgramCreateRequest, ProgramUpdateRequest)

_PRICE_MAX = Decimal("999999.99")

# A valid baseline for each field, used so that exactly one field is invalid at a
# time and the rejection is unambiguously attributable to that field.
_VALID_TITLE = "A valid program title"
_VALID_DESCRIPTION = "A valid description"
_VALID_PRICE = Decimal("49.99")


def _assert_rejected(**fields) -> None:
    """Both request models must reject the given fields with a ValidationError.

    A raised ``ValidationError`` means no validated request model is produced, so
    the service can never construct a ``ProgramRecord`` from it -- i.e. the
    invalid request is rejected "without storing".
    """
    for model in _REQUEST_MODELS:
        with pytest.raises(ValidationError):
            model(**fields)


# ──────────────────────────────────────────────────────────────────────────────
# Generators for invalid field values
# ──────────────────────────────────────────────────────────────────────────────

# Titles that are empty or whitespace-only -> empty after trimming (Req 2.1).
_blank_titles = st.text(alphabet=" \t\n\r\f\v", max_size=10)

# Titles that exceed 200 characters after trimming (Req 2.2). Use non-whitespace
# content so trimming does not shrink it below the limit.
_overlong_titles = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp")),
    min_size=201,
    max_size=400,
).filter(lambda s: len(s.strip()) > 200)

# Descriptions longer than 5,000 characters (Req 2.3). Built from a small count
# of excess characters padded onto the 5,000-char limit, rather than generating
# a 5,001+ char string directly -- the latter makes Hypothesis' smallest natural
# input very large and trips the large-base-example health check.
_overlong_descriptions = st.integers(min_value=1, max_value=200).map(
    lambda excess: "x" * (5000 + excess)
)

# Prices below 0.00 (Req 2.5, negative branch).
_negative_prices = st.decimals(
    min_value=Decimal("-100000"),
    max_value=Decimal("-0.01"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Prices strictly greater than 999,999.99 (Req 2.5, over-max branch).
_over_max_prices = st.decimals(
    min_value=Decimal("1000000.00"),
    max_value=Decimal("9999999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Prices carrying more than 2 fractional digits (Req 2.6 / 2.7). Keep the value
# within the accepted magnitude range so the ONLY reason for rejection is the
# excess fractional precision.
_too_precise_prices = st.decimals(
    min_value=Decimal("0"),
    max_value=_PRICE_MAX,
    places=4,
    allow_nan=False,
    allow_infinity=False,
).filter(lambda d: -d.as_tuple().exponent > 2)


# ──────────────────────────────────────────────────────────────────────────────
# Property 2
# ──────────────────────────────────────────────────────────────────────────────


@settings(max_examples=100)
@given(title=_blank_titles)
def test_empty_or_blank_title_is_rejected(title):
    """Feature: coaching-programs, Property 2: Invalid program fields are
    rejected without storing. A title that is empty or whitespace-only (empty
    after trimming) is rejected for both create and update.

    Validates: Requirements 2.1, 4.9
    """
    _assert_rejected(
        title=title, description=_VALID_DESCRIPTION, price=_VALID_PRICE
    )


@settings(max_examples=100)
@given(title=_overlong_titles)
def test_overlong_title_is_rejected(title):
    """Feature: coaching-programs, Property 2: Invalid program fields are
    rejected without storing. A title longer than 200 characters after trimming
    is rejected for both create and update.

    Validates: Requirements 2.2, 4.9
    """
    assume(len(title.strip()) > 200)
    _assert_rejected(
        title=title, description=_VALID_DESCRIPTION, price=_VALID_PRICE
    )


@settings(max_examples=100)
@given(description=_overlong_descriptions)
def test_overlong_description_is_rejected(description):
    """Feature: coaching-programs, Property 2: Invalid program fields are
    rejected without storing. A description longer than 5,000 characters is
    rejected for both create and update.

    Validates: Requirements 2.3, 4.9
    """
    _assert_rejected(
        title=_VALID_TITLE, description=description, price=_VALID_PRICE
    )


@settings(max_examples=100)
@given(price=st.one_of(_negative_prices, _over_max_prices))
def test_out_of_range_price_is_rejected(price):
    """Feature: coaching-programs, Property 2: Invalid program fields are
    rejected without storing. A price that is negative or greater than
    999,999.99 is rejected for both create and update.

    Validates: Requirements 2.5, 4.9
    """
    _assert_rejected(
        title=_VALID_TITLE, description=_VALID_DESCRIPTION, price=price
    )


@settings(max_examples=100)
@given(price=_too_precise_prices)
def test_price_with_excess_fractional_digits_is_rejected(price):
    """Feature: coaching-programs, Property 2: Invalid program fields are
    rejected without storing. A price carrying more than 2 fractional digits is
    rejected for both create and update.

    Validates: Requirements 2.6, 2.7, 4.9
    """
    assume(-price.as_tuple().exponent > 2)
    _assert_rejected(
        title=_VALID_TITLE, description=_VALID_DESCRIPTION, price=price
    )


@settings(max_examples=100)
@given(data=st.data())
def test_any_single_invalid_field_is_rejected(data):
    """Feature: coaching-programs, Property 2: Invalid program fields are
    rejected without storing. For an otherwise-valid request, corrupting any one
    field (title, description, or price) with an out-of-constraint value causes
    rejection for both create and update -- so no validated model, and therefore
    no stored Program, can result.

    Validates: Requirements 2.1, 2.2, 2.3, 2.5, 2.6, 2.7, 4.9
    """
    invalid_title = st.one_of(_blank_titles, _overlong_titles)
    invalid_price = st.one_of(
        _negative_prices, _over_max_prices, _too_precise_prices
    )

    field = data.draw(st.sampled_from(("title", "description", "price")))
    fields = {
        "title": _VALID_TITLE,
        "description": _VALID_DESCRIPTION,
        "price": _VALID_PRICE,
    }

    if field == "title":
        fields["title"] = data.draw(invalid_title)
        assume(len(fields["title"].strip()) > 200 or not fields["title"].strip())
    elif field == "description":
        fields["description"] = data.draw(_overlong_descriptions)
    else:
        fields["price"] = data.draw(invalid_price)

    _assert_rejected(**fields)
