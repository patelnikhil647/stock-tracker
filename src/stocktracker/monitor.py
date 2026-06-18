"""Orchestrate one monitoring cycle: fetch quotes, run the state machine, alert."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from . import notify, prices
from .config import Config, Watchlist
from .state import (
    EVENT_ALERT,
    EVENT_RECOVERED,
    EVENT_REMINDER,
    StateStore,
)

log = logging.getLogger("stocktracker")


@dataclass
class TickerResult:
    ticker: str
    price: Optional[float] = None
    week52_high: Optional[float] = None
    drop_pct: Optional[float] = None
    threshold: float = 0.0
    alerted: bool = False
    event: Optional[str] = None
    error: Optional[str] = None


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def run_cycle(config: Config, watchlist: Watchlist) -> list[TickerResult]:
    """Evaluate every watched ticker once. Sends alerts as needed.

    Returns a per-ticker result list for logging / the `status` command.
    """
    results: list[TickerResult] = []
    # Calendar date in the market timezone: the 52-week high is cached per day, so
    # this is the key that decides cache hit vs. a fresh year-of-bars fetch.
    today = datetime.now(ZoneInfo(config.market_hours.timezone)).date().isoformat()
    with StateStore(config.state_db) as store:
        for entry in watchlist.entries:
            threshold = entry.threshold if entry.threshold is not None else config.threshold
            result = TickerResult(ticker=entry.ticker, threshold=threshold)
            try:
                cached_high = store.get_cached_high(entry.ticker, today)
                quote = prices.get_quote(entry.ticker, cached_high=cached_high)
            except prices.PriceError as exc:
                result.error = str(exc)
                log.warning("price error for %s: %s", entry.ticker, exc)
                results.append(result)
                continue
            store.set_cached_high(entry.ticker, quote.week52_high, today)

            result.price = quote.price
            result.week52_high = quote.week52_high
            result.drop_pct = quote.drop_pct

            event = store.evaluate(entry.ticker, quote.drop_pct, threshold, today)
            result.event = event
            if event == EVENT_ALERT:
                _send_alert(config, quote, threshold)
                result.alerted = True
                log.info(
                    "ALERT %s down %.1f%% (%s -> %s)",
                    entry.ticker,
                    quote.drop_pct * 100,
                    _fmt_money(quote.week52_high),
                    _fmt_money(quote.price),
                )
            elif event == EVENT_REMINDER:
                _send_reminder(config, quote, threshold)
                result.alerted = True
                log.info(
                    "REMINDER %s still down %.1f%% (%s -> %s)",
                    entry.ticker,
                    quote.drop_pct * 100,
                    _fmt_money(quote.week52_high),
                    _fmt_money(quote.price),
                )
            elif event == EVENT_RECOVERED:
                _send_recovery(config, quote, threshold)
                log.info(
                    "RECOVERED %s back above threshold %.0f%% (now %s)",
                    entry.ticker,
                    threshold * 100,
                    _fmt_money(quote.price),
                )
            else:
                log.info(
                    "%s down %.1f%% (threshold %.0f%%) — no alert",
                    entry.ticker,
                    quote.drop_pct * 100,
                    threshold * 100,
                )
            results.append(result)
    return results


def _push(config: Config, ticker: str, *, title: str, message: str, tags: str) -> None:
    """Send one ntfy push; a notification failure never aborts the cycle."""
    try:
        notify.send(config.ntfy, title=title, message=message, tags=tags)
    except notify.NotifyError as exc:
        log.error("notification failed for %s: %s", ticker, exc)


def _send_alert(config: Config, quote: prices.Quote, threshold: float) -> None:
    title = f"{quote.ticker} down {quote.drop_pct * 100:.1f}%"
    message = (
        f"{quote.ticker} is {quote.drop_pct * 100:.1f}% below its 52-week high "
        f"(threshold {threshold * 100:.0f}%).\n"
        f"52-wk high {_fmt_money(quote.week52_high)} -> now {_fmt_money(quote.price)}"
    )
    _push(config, quote.ticker, title=title, message=message, tags="chart_with_downwards_trend")


def _send_reminder(config: Config, quote: prices.Quote, threshold: float) -> None:
    title = f"{quote.ticker} still down {quote.drop_pct * 100:.1f}%"
    message = (
        f"{quote.ticker} remains {quote.drop_pct * 100:.1f}% below its 52-week high "
        f"(threshold {threshold * 100:.0f}%).\n"
        f"52-wk high {_fmt_money(quote.week52_high)} -> now {_fmt_money(quote.price)}"
    )
    _push(config, quote.ticker, title=title, message=message, tags="chart_with_downwards_trend")


def _send_recovery(config: Config, quote: prices.Quote, threshold: float) -> None:
    title = f"{quote.ticker} recovered"
    message = (
        f"{quote.ticker} is back above the {threshold * 100:.0f}% threshold.\n"
        f"52-wk high {_fmt_money(quote.week52_high)} -> now {_fmt_money(quote.price)}"
    )
    _push(config, quote.ticker, title=title, message=message, tags="chart_with_upwards_trend")
