import pytest

from acg.domain.category import normalise_category


class TestNormaliseCategory:
    def test_lowercases(self) -> None:
        assert normalise_category("SkinCare") == "skincare"

    def test_strips_surrounding_whitespace(self) -> None:
        assert normalise_category("  skincare  ") == "skincare"

    def test_is_idempotent(self) -> None:
        once = normalise_category("  SkinCare ")

        assert normalise_category(once) == once

    def test_casefolds_beyond_ascii(self) -> None:
        # casefold, not lower: a merchant feed is not guaranteed to be ASCII,
        # and lower() leaves cases like this one unmatched.
        assert normalise_category("STRASSE") == normalise_category("Straße")

    def test_rejects_a_blank_name(self) -> None:
        with pytest.raises(ValueError, match="must not be blank"):
            normalise_category("   ")

    def test_rejects_a_non_string(self) -> None:
        with pytest.raises(ValueError, match="must be a str"):
            normalise_category(42)
