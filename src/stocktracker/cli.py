"""Command-line entrypoint: `stocktracker <command>` or `python -m stocktracker`."""

from __future__ import annotations

import argparse
import logging
import sys

from . import config as cfg
from . import monitor, notify, prices
from .state import StateStore


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def cmd_check(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    if not config.market_hours.is_open():
        logging.info("Market closed — skipping check (set market_hours.enabled: false to override).")
        return 0
    watchlist = cfg.load_watchlist()
    if not watchlist.entries:
        logging.warning("Watchlist is empty. Add tickers with `stocktracker add <TICKER>`.")
        return 0
    monitor.run_cycle(config, watchlist)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    added = cfg.add_ticker(args.ticker)
    ticker = args.ticker.strip().upper()
    print(f"Added {ticker}." if added else f"{ticker} is already on the watchlist.")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    removed = cfg.remove_ticker(args.ticker)
    ticker = args.ticker.strip().upper()
    print(f"Removed {ticker}." if removed else f"{ticker} is not on the watchlist.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    watchlist = cfg.load_watchlist()
    if not watchlist.entries:
        print("Watchlist is empty.")
        return 0
    config = cfg.load_config()
    for e in watchlist.entries:
        thr = e.threshold if e.threshold is not None else config.threshold
        print(f"  {e.ticker:<8} threshold {thr * 100:.0f}%")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    watchlist = cfg.load_watchlist()
    if not watchlist.entries:
        print("Watchlist is empty.")
        return 0
    print(f"{'TICKER':<8}{'PRICE':>12}{'52WK HIGH':>14}{'DROP':>8}{'STATE':>12}")
    with StateStore(config.state_db) as store:
        for e in watchlist.entries:
            thr = e.threshold if e.threshold is not None else config.threshold
            st = store.get(e.ticker).state
            try:
                q = prices.get_quote(e.ticker)
            except prices.PriceError as exc:
                print(f"{e.ticker:<8}{'error: ' + str(exc)}")
                continue
            flag = " *" if q.drop_pct >= thr else ""
            print(
                f"{e.ticker:<8}{'$%.2f' % q.price:>12}{'$%.2f' % q.week52_high:>14}"
                f"{'%.1f%%' % (q.drop_pct * 100):>8}{st:>12}{flag}"
            )
    return 0


def cmd_test_notify(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    try:
        notify.send(
            config.ntfy,
            title="✅ stock-tracker test",
            message="If you can read this on your phone, ntfy is working.",
            tags="white_check_mark",
        )
    except notify.NotifyError as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    print(f"Sent test notification to topic '{config.ntfy.topic}' on {config.ntfy.server}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stocktracker", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Run one monitoring cycle (this is what cron calls)")
    p_add = sub.add_parser("add", help="Add a ticker to the watchlist")
    p_add.add_argument("ticker")
    p_rm = sub.add_parser("remove", help="Remove a ticker from the watchlist")
    p_rm.add_argument("ticker")
    sub.add_parser("list", help="List watched tickers and thresholds")
    sub.add_parser("status", help="Show current price, 52wk high, drop %, and state")
    sub.add_parser("test-notify", help="Send a test notification to your phone")

    return parser


_HANDLERS = {
    "check": cmd_check,
    "add": cmd_add,
    "remove": cmd_remove,
    "list": cmd_list,
    "status": cmd_status,
    "test-notify": cmd_test_notify,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
