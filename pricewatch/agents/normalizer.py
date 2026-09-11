"""Normalizer agent: turns whatever a page printed into (minor units, ISO currency).

Storefronts print money in a dozen ways. Everything downstream (history, alerts, the
dashboard) assumes `price_cents` is an int in the store's currency. This is the only place
that should know about currency symbols and locale formatting.
"""
from __future__ import annotations

import re
from typing import Optional

SYMBOLS = {
    "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "kr": "SEK", "¥": "JPY", "CHF": "CHF",
}
CODES = {"USD", "EUR", "GBP", "INR", "SEK", "NOK", "DKK", "JPY", "CHF", "CAD", "AUD"}


def detect_currency(text: str, default: Optional[str] = None) -> Optional[str]:
    t = text.strip()
    for code in CODES:
        if re.search(rf"\b{code}\b", t):
            return code
    for sym, code in sorted(SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        if sym in t:
            return code
    return default


def parse_money(text: str, default_currency: Optional[str] = None) -> tuple[Optional[int], Optional[str]]:
    """Parse a printed price like "$1,299.00" into (129900, "USD").

    Returns (None, currency) when no number is present.
    """
    if text is None:
        return None, default_currency
    currency = detect_currency(text, default_currency)
    num_str = re.sub(r"[^\d.,]", "", text)
    if not num_str or num_str in (".", ","):
        return None, currency
        
    if re.search(r",\d{1,2}$", num_str):
        num_str = num_str.replace(".", "").replace(",", ".")
    elif re.search(r"\.\d{1,2}$", num_str):
        num_str = num_str.replace(",", "")
    else:
        num_str = num_str.replace(",", "").replace(".", "")
        
    try:
        amount = float(num_str)
    except ValueError:
        return None, currency
    return int(round(amount * 100)), currency


def unit_price(price_cents: Optional[int], pack_size: int) -> Optional[int]:
    if price_cents is None or pack_size <= 1:
        return None
    return int(round(price_cents / pack_size))
