"""Orchestrate one monitoring cycle: fetch quotes, run the state machine, alert."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from . import notify, prices
from .config import Config, Watchlist
from .state import StateStore

log = logging.getLogger("stocktracker")


@dataclass
class TickerResult:
    ticker: str
    price: Optional[float] = None
    week52_high: Optional[float] = None
    drop_pct: Optional[float] = None
    threshold: float = 0.0
    alerted: bool = False
    error: Optional[str] = None


def _fmt_money(value: float) -> str:
    return f"${value:,.2f}"


def run_cycle(config: Config, watchlist: Watchlist) -> list[TickerResult]:
    """Evaluate every watched ticker once. Sends alerts as needed.

    Returns a per-ticker result list for logging / the `status` command.
    """
    results: list[TickerResult] = []
    with StateStore(config.state_db) as store:
        for entry in watchlist.entries:
            threshold = entry.threshold if entry.threshold is not None else config.threshold
            result = TickerResult(ticker=entry.ticker, threshold=threshold)
            try:
                quote = prices.get_quote(entry.ticker)
            except prices.PriceError as exc:
                result.error = str(exc)
                log.warning("price error for %s: %s", entry.ticker, exc)
                results.append(result)
                continue

            result.price = quote.price
            result.week52_high = quote.week52_high
            result.drop_pct = quote.drop_pct

            should_alert = store.evaluate(entry.ticker, quote.drop_pct, threshold)
            if should_alert:
                _send_alert(config, quote, threshold)
                result.alerted = True
                log.info(
                    "ALERT %s down %.1f%% (%s -> %s)",
                    entry.ticker,
                    quote.drop_pct * 100,
                    _fmt_money(quote.week52_high),
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


def _send_alert(config: Config, quote: prices.Quote, threshold: float) -> None:
    title = f"\U0001F4C9 {quote.ticker} down {quote.drop_pct * 100:.1f}%"
    message = (
        f"{quote.ticker} is {quote.drop_pct * 100:.1f}% below its 52-week high "
        f"(threshold {threshold * 100:.0f}%).\n"
        f"52-wk high {_fmt_money(quote.week52_high)} -> now {_fmt_money(quote.price)}"
    )
    try:
        notify.send(config.ntfy, title=title, message=message, tags="chart_with_downwards_trend")
    except notify.NotifyError as exc:
        # Don't let a notification failure abort the rest of the cycle.
        log.error("notification failed for %s: %s", quote.ticker, exc)
