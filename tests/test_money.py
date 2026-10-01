from src.utils.money import MINUS, format_money


def test_format_money_negative_uses_true_minus_before_dollar() -> None:
    assert format_money(-1234.56) == f"{MINUS}$1,234.56"


def test_format_money_signed_and_zero() -> None:
    assert format_money(12, signed=True) == "+$12.00"
    assert format_money(12) == "$12.00"
    assert format_money(0, signed=True) == "$0.00"
    assert format_money(-0.001, signed=True) == "$0.00"


def test_format_money_whole_dollars() -> None:
    assert format_money(-1234.6, cents=False) == f"{MINUS}$1,235"
