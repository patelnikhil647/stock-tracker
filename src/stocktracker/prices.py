"""Fetch current price and 52-week high for tickers via yfinance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import yfinance as yf


@dataclass
class Quote:
    ticker: str
    price: float
    week52_high: float

    @property
    def drop_pct(self) -> float:
        """Fractional drop from the 52-week high (0.16 == 16% below high)."""
        if self.week52_high <= 0:
            return 0.0
        return (self.week52_high - self.price) / self.week52_high


class PriceError(Exception):
    """Raised when a usable quote cannot be obtained for a ticker."""


def get_quote(ticker: str) -> Quote:
    """Return a Quote for `ticker`.

    Prefers yfinance `fast_info` (fast, reliable). Falls back to computing the
    52-week high and last close from ~1 year of daily history when fast_info is
    missing fields.
    """
    ticker = ticker.strip().upper()
    t = yf.Ticker(ticker)

    price = _from_fast_info(t, ("last_price", "lastPrice"))
    high = _from_fast_info(t, ("year_high", "yearHigh"))

    if price is None or high is None or high <= 0:
        hist_price, hist_high = _from_history(t)
        price = price if (price is not None and price > 0) else hist_price
        high = high if (high is not None and high > 0) else hist_high

    if price is None or price <= 0 or high is None or high <= 0:
        raise PriceError(f"Could not obtain a usable quote for {ticker}")

    return Quote(ticker=ticker, price=float(price), week52_high=float(high))


def _from_fast_info(t: "yf.Ticker", keys: tuple[str, ...]) -> Optional[float]:
    try:
        fi = t.fast_info
    except Exception:
        return None
    for key in keys:
        try:
            value = fi[key] if _supports_getitem(fi) else getattr(fi, key, None)
        except (KeyError, AttributeError, Exception):
            value = None
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _supports_getitem(obj) -> bool:
    return hasattr(obj, "__getitem__")


def _from_history(t: "yf.Ticker") -> tuple[Optional[float], Optional[float]]:
    """Return (last_close, max_high) from ~1y of daily history, or (None, None)."""
    try:
        hist = t.history(period="1y", interval="1d", auto_adjust=False)
    except Exception:
        return None, None
    if hist is None or hist.empty:
        return None, None
    try:
        last_close = float(hist["Close"].dropna().iloc[-1])
        max_high = float(hist["High"].dropna().max())
    except (KeyError, IndexError, ValueError):
        return None, None
    return last_close, max_high
