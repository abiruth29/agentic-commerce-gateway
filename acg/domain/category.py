"""One normalisation for category names, used by every side that compares them.

A mandate authorises "Skincare" and an item declares "skincare". Whether those
match decides an I1 outcome, so the comparison must not depend on which side
happened to normalise, or how. Two copies of this logic that drift apart is not
a tidiness problem — it is the bypass.

So there is exactly one function, and both the mandate and the catalog run
their input through it at construction. By the time any rule compares two
categories, both are already in the same form.
"""


def normalise_category(value: object) -> str:
    """Return the canonical form of a single category name.

    Raises ValueError rather than TypeError on bad input: pydantic converts
    ValueError and AssertionError into ValidationError and lets anything else
    escape the model, and a caller handling malformed input should not have to
    catch two exception types.
    """
    if not isinstance(value, str):
        raise ValueError(f"category must be a str, got {type(value).__name__}")

    # casefold rather than lower: it handles the cases lower() misses, and a
    # category name arriving from a merchant feed is not guaranteed to be ASCII.
    cleaned = value.strip().casefold()
    if not cleaned:
        raise ValueError("category must not be blank")
    return cleaned
