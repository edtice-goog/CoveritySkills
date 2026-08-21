/* Pricing rule from the spec: orders of 100 units OR MORE get the bulk
 * discount. The comparison below uses '>' instead of '>=', so an order of
 * exactly 100 units is wrongly charged full price. */
int unit_price_cents(int quantity)
{
    const int full_price = 500;
    const int bulk_price = 425;

    if (quantity > 100)
    {
        return bulk_price;
    }
    return full_price;
}
