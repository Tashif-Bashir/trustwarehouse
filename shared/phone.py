"""Phone number normalisation — UK numbers to pure digits with country code."""


def normalise_phone(raw: str | None) -> str | None:
    """Normalise a UK phone number to pure digits with country code prefix.

    Strips all non-digit characters, then:
    - '00...' → strips the leading '00'
    - '0...'  → replaces leading '0' with '44'
    - anything else → returned as-is (digits only)

    Returns None for empty, None, or non-numeric input.
    """
    if not raw:
        return None
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits
