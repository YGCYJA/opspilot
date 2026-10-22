"""A small shopping-cart rule used by the reproducible pytest example."""
from decimal import Decimal


def total_after_discount(subtotal: Decimal) -> Decimal:
    """Apply a fixed 10.00 discount to orders of at least 100.00."""
    if not isinstance(subtotal, Decimal):
        raise TypeError("subtotal must be Decimal")
    if subtotal < Decimal("0"):
        raise ValueError("subtotal must not be negative")
    if subtotal >= Decimal("100.00"):
        return subtotal - Decimal("10.00")
    return subtotal
