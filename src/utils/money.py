"""Money formatting shared by every view.

One format everywhere: a true minus (U+2212) before the dollar sign for
negatives (U+2212 then "$1,234.56"), and with ``signed=True`` a "+" for positives
("+$12.00"). Never "$-5.00" or an ASCII hyphen.
"""

from __future__ import annotations

MINUS = "−"


def format_money(amount: float, *, signed: bool = False, cents: bool = True) -> str:
    """Format ``amount`` as dollars.

    ``signed`` adds "+" to positive amounts (deltas, transaction amounts).
    Zero never takes a sign. ``cents=False`` rounds to whole dollars.
    """
    body = f"${abs(amount):,.2f}" if cents else f"${abs(amount):,.0f}"
    rounded = round(amount, 2 if cents else 0)
    if rounded < 0:
        return MINUS + body
    if signed and rounded > 0:
        return "+" + body
    return body
