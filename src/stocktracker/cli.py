"""Command-line entrypoint: `stocktracker <command>` or `python -m stocktracker`."""

from __future__ import annotations

import argparse
import logging
import sys

from . import config as cfg
from . import monitor, notify, prices, templates
from .state import StateStore


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def cmd_init(args: argparse.Namespace) -> int:
    """Create config.yaml (random topics) and watchlist.yaml (VOO) for a fresh setup."""
    return run_init(
        cfg.CONFIG_PATH, cfg.WATCHLIST_PATH, force=args.force, out=sys.stdout
    )


def run_init(config_path, watchlist_path, *, force: bool = False, out=sys.stdout) -> int:
    existing = [p for p in (config_path, watchlist_path) if p.exists()]
    if existing and not force:
        names = ", ".join(p.name for p in existing)
        print(
            f"Refusing to overwrite existing {names}. Re-run with --force to replace.",
            file=sys.stderr,
        )
        return 1

    alert_topic = templates.random_topic()
    command_topic = templates.random_topic()
    config_path.write_text(templates.render_config(alert_topic, command_topic))
    watchlist_path.write_text(templates.DEFAULT_WATCHLIST)

    print(f"Created {config_path.name} and {watchlist_path.name}.", file=out)
    print(f"  alert topic:   {alert_topic}", file=out)
    print(f"  command topic: {command_topic}", file=out)
    print(
        "\nNext: install the ntfy app on your phone and subscribe to the alert "
        f"topic '{alert_topic}', then run `stocktracker test-notify`.",
        file=out,
    )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config = cfg.load_config()
    if not args.ignore_market_hours and not config.market_hours.is_open():
        logging.info("Market closed — skipping check (use -i/--ignore-market-hours to force).")
        return 0
    watchlist = cfg.load_watchlist()
    if not watchlist.entries:
        logging.warning("Watchlist is empty. Add tickers with `stocktracker add <TICKER>`.")
        return 0
    monitor.run_cycle(config, watchlist)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Add one or more tickers, validating each via yfinance first."""
    had_error = False
    for raw in args.tickers:
        ticker = raw.strip().upper()
        try:
            prices.get_quote(ticker)
        except prices.PriceError:
            print(f"Warning: could not resolve '{ticker}' — skipping.", file=sys.stderr)
            had_error = True
            continue
        added = cfg.add_ticker(ticker)
        print(f"Added {ticker}." if added else f"{ticker} is already on the watchlist.")
    return 1 if had_error else 0


def cmd_remove(args: argparse.Namespace) -> int:
    """Remove one or more tickers, warning on any not present."""
    had_error = False
    removed: list[str] = []
    for raw in args.tickers:
        ticker = raw.strip().upper()
        if cfg.remove_ticker(ticker):
            print(f"Removed {ticker}.")
            removed.append(ticker)
        else:
            print(f"Warning: {ticker} is not on the watchlist — skipping.", file=sys.stderr)
            had_error = True
    _cleanup_state(removed)
    return 1 if had_error else 0


def _cleanup_state(tickers: list[str]) -> None:
    """Delete state rows for removed tickers (best-effort; skipped if no config)."""
    if not tickers:
        return
    try:
        state_db = cfg.load_config().state_db
    except Exception:
        return  # config not set up yet — nothing to clean
    with StateStore(state_db) as store:
        for ticker in tickers:
            store.delete(ticker)


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
            title="stock-tracker test",
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

    p_init = sub.add_parser("init", help="Create config.yaml and watchlist.yaml for a fresh setup")
    p_init.add_argument(
        "-f", "--force", action="store_true", help="Overwrite existing config/watchlist files."
    )
    p_check = sub.add_parser("check", help="Run one monitoring cycle (this is what cron calls)")
    p_check.add_argument(
        "-i",
        "--ignore-market-hours",
        action="store_true",
        help="Run the cycle even when the market is closed (for manual testing).",
    )
    p_add = sub.add_parser("add", help="Add one or more tickers to the watchlist")
    p_add.add_argument("tickers", nargs="+", metavar="TICKER")
    p_rm = sub.add_parser("remove", help="Remove one or more tickers from the watchlist")
    p_rm.add_argument("tickers", nargs="+", metavar="TICKER")
    sub.add_parser("list", help="List watched tickers and thresholds")
    sub.add_parser("status", help="Show current price, 52wk high, drop %%, and state")
    sub.add_parser("test-notify", help="Send a test notification to your phone")

    return parser


_HANDLERS = {
    "init": cmd_init,
    "check": cmd_check,
    "add": cmd_add,
    "remove": cmd_remove,
    "list": cmd_list,
    "status": cmd_status,
    "test-notify": cmd_test_notify,
}


def main(argv: list[str] | None = None) -> int:
    cfg.load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
