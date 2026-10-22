"""Five small tests of a documented, intentionally simple business rule."""
from decimal import Decimal

import pytest

from cart import total_after_discount


def test_no_discount_below_threshold():
    assert total_after_discount(Decimal("99.99")) == Decimal("99.99")


def test_discount_at_threshold():
    assert total_after_discount(Decimal("100.00")) == Decimal("90.00")


def test_discount_above_threshold():
    assert total_after_discount(Decimal("120.00")) == Decimal("110.00")


def test_rejects_negative_subtotal():
    with pytest.raises(ValueError, match="must not be negative"):
        total_after_discount(Decimal("-0.01"))


def test_rejects_float_subtotal():
    with pytest.raises(TypeError, match="must be Decimal"):
        total_after_discount(100.0)
