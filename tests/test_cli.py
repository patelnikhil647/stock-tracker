import argparse

from stocktracker import cli
from stocktracker.cli import build_parser
from stocktracker.prices import PriceError, Quote


def test_check_defaults_to_respecting_market_hours():
    args = build_parser().parse_args(["check"])
    assert args.ignore_market_hours is False


def test_check_short_flag_sets_ignore():
    args = build_parser().parse_args(["check", "-i"])
    assert args.ignore_market_hours is True


def test_check_long_flag_sets_ignore():
    args = build_parser().parse_args(["check", "--ignore-market-hours"])
    assert args.ignore_market_hours is True


def test_add_accepts_multiple_tickers():
    args = build_parser().parse_args(["add", "VOO", "SCHD", "NVDA"])
    assert args.tickers == ["VOO", "SCHD", "NVDA"]


def test_remove_accepts_multiple_tickers():
    args = build_parser().parse_args(["remove", "VOO", "SCHD"])
    assert args.tickers == ["VOO", "SCHD"]


def test_cmd_add_validates_and_skips_unresolvable(monkeypatch):
    added: list[str] = []

    def fake_quote(ticker):
        if ticker == "BOGUS":
            raise PriceError("no data")
        return Quote(ticker=ticker, price=10.0, week52_high=20.0)

    monkeypatch.setattr(cli.prices, "get_quote", fake_quote)
    monkeypatch.setattr(cli.cfg, "add_ticker", lambda t: added.append(t) or True)

    rc = cli.cmd_add(argparse.Namespace(tickers=["VOO", "BOGUS", "NVDA"]))

    assert added == ["VOO", "NVDA"]  # BOGUS skipped, never added
    assert rc == 1  # non-zero because one ticker failed


def test_cmd_remove_warns_on_absent_and_cleans_state(monkeypatch):
    present = {"VOO"}
    deleted: list[str] = []

    monkeypatch.setattr(cli.cfg, "remove_ticker", lambda t: t in present)
    monkeypatch.setattr(cli, "_cleanup_state", lambda tickers: deleted.extend(tickers))

    rc = cli.cmd_remove(argparse.Namespace(tickers=["VOO", "MISSING"]))

    assert deleted == ["VOO"]  # only the actually-removed ticker is cleaned up
    assert rc == 1  # MISSING was not present
