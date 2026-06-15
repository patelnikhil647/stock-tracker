"""Fetch current price and 52-week high for tickers.

Prefers Alpaca's market-data API (set ``APCA_API_KEY_ID`` / ``APCA_API_SECRET_KEY``
in the environment) and falls back to yfinance when Alpaca errors or no key is
set. The public contract — :class:`Quote`, :class:`PriceError`, :func:`get_quote`
— is provider-agnostic; callers do not know or care which source served a quote.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
import yfinance as yf

log = logging.getLogger("stocktracker.prices")

# yfinance logs its own noisy ERROR lines (HTTP 404 / "possibly delisted") for
# unknown symbols. We surface a clean PriceError instead, so silence its logger.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

# Alpaca defaults. The free data tier uses the IEX feed; override via env if you
# have a paid SIP subscription.
_ALPACA_DEFAULT_URL = "https://data.alpaca.markets"
_ALPACA_DEFAULT_FEED = "iex"

# Reused across calls so repeated requests reuse the same TCP/TLS connection
# (keep-alive) instead of paying a fresh handshake every time.
_SESSION = requests.Session()


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


def get_quote(ticker: str, cached_high: Optional[float] = None) -> Quote:
    """Return a Quote for `ticker`, preferring Alpaca and falling back to yfinance.

    Alpaca is tried first. If it errors (network, bad payload, unknown symbol) or
    no credentials are configured, we fall back to yfinance. A genuinely unknown
    ticker fails through both providers and raises PriceError.

    When `cached_high` is supplied (and > 0), Alpaca skips the year-of-bars fetch
    and reuses it as the 52-week high, fetching only the latest price — see
    `_alpaca_quote`. The yfinance fallback ignores it and returns its own values.
    """
    ticker = ticker.strip().upper()
    try:
        quote = _alpaca_quote(ticker, cached_high=cached_high)
        log.debug("quote for %s served by Alpaca", ticker)
        return quote
    except PriceError as exc:
        log.debug("Alpaca quote failed for %s (%s); falling back to yfinance", ticker, exc)
        quote = _yfinance_quote(ticker)
        log.debug("quote for %s served by yfinance", ticker)
        return quote


# --- Alpaca provider ---------------------------------------------------------


def _alpaca_quote(ticker: str, cached_high: Optional[float] = None) -> Quote:
    """Return a Quote from Alpaca's market-data API, or raise PriceError.

    When `cached_high` is supplied (and > 0), the year-of-bars fetch is skipped and
    that value is reused as the 52-week high; only the latest-price snapshot is
    requested. This is the fast path for the recurring `check` cycle.
    """
    key_id = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key_id or not secret:
        raise PriceError("Alpaca credentials not set")

    base = os.environ.get("APCA_API_DATA_URL", _ALPACA_DEFAULT_URL).rstrip("/")
    feed = os.environ.get("ALPACA_DATA_FEED", _ALPACA_DEFAULT_FEED)
    headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret}

    if cached_high is not None and cached_high > 0:
        high = float(cached_high)
    else:
        high = _alpaca_week52_high(base, feed, headers, ticker)
    price = _alpaca_latest_price(base, feed, headers, ticker)

    if price is None or price <= 0 or high <= 0:
        raise PriceError(f"Alpaca returned no usable quote for {ticker}")
    return Quote(ticker=ticker, price=float(price), week52_high=float(high))


def _alpaca_get(url: str, params: dict, headers: dict) -> dict:
    try:
        resp = _SESSION.get(url, params=params, headers=headers, timeout=15)
    except requests.RequestException as exc:
        raise PriceError(f"Alpaca request failed: {exc}") from exc
    if resp.status_code != 200:
        raise PriceError(f"Alpaca HTTP {resp.status_code} for {url}")
    try:
        return resp.json()
    except ValueError as exc:
        raise PriceError(f"Alpaca returned non-JSON for {url}") from exc


def _alpaca_week52_high(base: str, feed: str, headers: dict, ticker: str) -> float:
    """Max daily-bar high over ~1 year of history (Alpaca has no 52wk field)."""
    start = (datetime.now(timezone.utc) - timedelta(days=365)).date().isoformat()
    data = _alpaca_get(
        f"{base}/v2/stocks/{ticker}/bars",
        {
            "timeframe": "1Day",
            "start": start,
            "adjustment": "all",
            "feed": feed,
            "limit": 1000,
        },
        headers,
    )
    bars = data.get("bars") or []
    highs = [bar["h"] for bar in bars if bar.get("h") is not None]
    if not highs:
        raise PriceError(f"Alpaca returned no bars for {ticker}")
    return float(max(highs))


def _alpaca_latest_price(base: str, feed: str, headers: dict, ticker: str) -> Optional[float]:
    """Latest trade price, falling back to the latest daily close."""
    data = _alpaca_get(
        f"{base}/v2/stocks/{ticker}/snapshot", {"feed": feed}, headers
    )
    latest_trade = data.get("latestTrade") or {}
    price = latest_trade.get("p")
    if price is None:
        daily_bar = data.get("dailyBar") or {}
        price = daily_bar.get("c")
    return float(price) if price is not None else None


# --- yfinance provider (fallback) --------------------------------------------


def _yfinance_quote(ticker: str) -> Quote:
    """Return a Quote for `ticker` via yfinance.

    Prefers yfinance `fast_info` (fast, reliable). Falls back to computing the
    52-week high and last close from ~1 year of daily history when fast_info is
    missing fields.
    """
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
