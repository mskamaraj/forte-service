"""Property-based test for the stored program price scale.

Feature: coaching-programs, Property 3: Stored program price has exactly two
fractional digits. For any valid program create/update request whose price lies
in [0.00, 999999.99] with at most 2 fractional digits, the validated model's
price is normalized to a Decimal with exactly 2 fractional digits -- i.e. the
value the service persists as the Program price (Requirement 2.8) always has
scale 2, regardless of how many fractional digits the input carried.

``ProgramCreateRequest`` and ``ProgramUpdateRequest`` (its subclass) share the
same ``price`` validator, so the invariant is asserted against both, covering
the create path and the owner-update path with the same generators.

Validates: Requirements 2.8
"""

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.program import ProgramCreateRequest, ProgramUpdateRequest

# Both request models share the Requirement 2 price validator (update subclasses
# create), so the scale invariant must hold for both.
_REQUEST_MODELS = (ProgramCreateRequest, ProgramUpdateRequest)

_PRICE_MIN = Decimal("0.00")
_PRICE_MAX = Decimal("999999.99")

_VALID_TITLE = "A valid program title"
_VALID_DESCRIPTION = "A valid description"


def _fractional_digits(value: Decimal) -> int:
    """Number of fractional digits of a Decimal (0 for integral exponents)."""
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


# Valid prices in [0.00, 999999.99] carrying at most 2 fractional digits. The
# ``places`` parameter is sampled so inputs range over 0, 1, and 2 fractional
# digits -- each must normalize to exactly scale 2.
_valid_prices = st.integers(min_value=0, max_value=2).flatmap(
    lambda places: st.decimals(
        min_value=_PRICE_MIN,
        max_value=_PRICE_MAX,
        places=places,
        allow_nan=False,
        allow_infinity=False,
    )
)


@settings(max_examples=200)
@given(price=_valid_prices)
def test_stored_price_has_exactly_two_fractional_digits(price):
    """Feature: coaching-programs, Property 3: Stored program price has exactly
    two fractional digits. A valid price (0.00-999999.99, <=2 fractional digits)
    is normalized by the request model to a Decimal with exactly scale 2, so the
    value the service stores as the Program price always has two fractional
    digits.

    Validates: Requirements 2.8
    """
    assert _fractional_digits(price) <= 2

    for model in _REQUEST_MODELS:
        request = model(
            title=_VALID_TITLE, description=_VALID_DESCRIPTION, price=price
        )
        stored = request.price
        # Exactly two fractional digits: exponent of a scale-2 Decimal is -2.
        assert stored.as_tuple().exponent == -2
        assert _fractional_digits(stored) == 2
        # Normalization preserves numeric value (no rounding of valid inputs).
        assert stored == price
