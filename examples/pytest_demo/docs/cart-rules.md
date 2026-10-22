# Shopping cart discount rules

This is a deliberately small demonstration project. The amounts and rules are
invented for the example; they do not describe a production shop.

## Amount representation

`total_after_discount` accepts a non-negative `decimal.Decimal` amount. A float
is rejected to avoid binary floating-point amounts in the cart API. A negative
amount is rejected with `ValueError`.

## Inclusive discount threshold

An order with a subtotal of **at least 100.00** receives exactly **10.00** off.
The threshold is inclusive: a subtotal of exactly 100.00 must produce a payable
total of 90.00. An amount below the threshold receives no discount. Discounts
do not stack or repeat for larger orders.

`test_discount_at_threshold` protects the exact boundary. The neighboring
`test_no_discount_below_threshold` and `test_discount_above_threshold` cases
check 99.99 and 120.00 respectively.
