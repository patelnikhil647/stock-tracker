import pytest

from stocktracker import prices
from stocktracker.prices import PriceError, Quote


def test_drop_pct_basic():
    q = Quote(ticker="VOO", price=85.0, week52_high=100.0)
    assert abs(q.drop_pct - 0.15) < 1e-9


def test_drop_pct_at_high_is_zero():
    q = Quote(ticker="VOO", price=100.0, week52_high=100.0)
    assert q.drop_pct == 0.0


def test_drop_pct_above_high_is_negative():
    # Price made a new high mid-session; drop is negative (not below the line).
    q = Quote(ticker="VOO", price=110.0, week52_high=100.0)
    assert q.drop_pct < 0


def test_drop_pct_guards_zero_high():
    q = Quote(ticker="VOO", price=50.0, week52_high=0.0)
    assert q.drop_pct == 0.0


# --- Alpaca provider ---------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _alpaca_creds(monkeypatch):
    monkeypatch.setenv("APCA_API_KEY_ID", "key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "secret")


def _fake_get(routes):
    """Return a requests.get stub that dispatches on a substring of the URL."""

    def _get(url, params=None, headers=None, timeout=None):
        for needle, payload in routes.items():
            if needle in url:
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected URL {url}")

    return _get


def test_alpaca_quote_parses_snapshot_and_bars(monkeypatch):
    _alpaca_creds(monkeypatch)
    monkeypatch.setattr(
        prices._SESSION,
        "get",
        _fake_get(
            {
                "/snapshot": {"latestTrade": {"p": 90.0}, "dailyBar": {"c": 88.0}},
                "/bars": {"bars": [{"h": 100.0}, {"h": 120.0}, {"h": 110.0}]},
            }
        ),
    )
    q = prices._alpaca_quote("VOO")
    assert q.ticker == "VOO"
    assert q.price == 90.0
    assert q.week52_high == 120.0  # max of the bar highs


def test_alpaca_quote_falls_back_to_daily_close_when_no_trade(monkeypatch):
    _alpaca_creds(monkeypatch)
    monkeypatch.setattr(
        prices._SESSION,
        "get",
        _fake_get(
            {
                "/snapshot": {"latestTrade": {}, "dailyBar": {"c": 88.0}},
                "/bars": {"bars": [{"h": 100.0}]},
            }
        ),
    )
    q = prices._alpaca_quote("VOO")
    assert q.price == 88.0


def test_alpaca_quote_unknown_symbol_raises(monkeypatch):
    _alpaca_creds(monkeypatch)
    monkeypatch.setattr(
        prices._SESSION,
        "get",
        _fake_get({"/bars": {"bars": None}, "/snapshot": {}}),
    )
    with pytest.raises(PriceError):
        prices._alpaca_quote("NOPE")


def test_alpaca_quote_no_creds_raises(monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    with pytest.raises(PriceError):
        prices._alpaca_quote("VOO")


# --- Provider chain (get_quote) ----------------------------------------------


def test_get_quote_falls_back_to_yfinance_without_creds(monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    sentinel = Quote(ticker="VOO", price=80.0, week52_high=100.0)
    monkeypatch.setattr(prices, "_yfinance_quote", lambda ticker: sentinel)
    assert prices.get_quote("voo") is sentinel


def test_get_quote_falls_back_when_alpaca_errors(monkeypatch):
    _alpaca_creds(monkeypatch)

    def _boom(ticker, cached_high=None):
        raise PriceError("alpaca down")

    sentinel = Quote(ticker="VOO", price=70.0, week52_high=100.0)
    monkeypatch.setattr(prices, "_alpaca_quote", _boom)
    monkeypatch.setattr(prices, "_yfinance_quote", lambda ticker: sentinel)
    assert prices.get_quote("VOO") is sentinel


def test_get_quote_prefers_alpaca(monkeypatch):
    alpaca_q = Quote(ticker="VOO", price=95.0, week52_high=100.0)
    monkeypatch.setattr(prices, "_alpaca_quote", lambda ticker, cached_high=None: alpaca_q)
    monkeypatch.setattr(
        prices, "_yfinance_quote", lambda ticker: pytest.fail("should not reach yfinance")
    )
    assert prices.get_quote("VOO") is alpaca_q


def test_get_quote_forwards_cached_high(monkeypatch):
    seen = {}

    def _capture(ticker, cached_high=None):
        seen["cached_high"] = cached_high
        return Quote(ticker=ticker, price=90.0, week52_high=cached_high or 0.0)

    monkeypatch.setattr(prices, "_alpaca_quote", _capture)
    prices.get_quote("VOO", cached_high=120.0)
    assert seen["cached_high"] == 120.0


# --- cached_high fast path (skips the bars call) -----------------------------


def test_alpaca_quote_with_cached_high_skips_bars(monkeypatch):
    _alpaca_creds(monkeypatch)
    requested = []

    def _get(url, params=None, headers=None, timeout=None):
        requested.append(url)
        assert "/bars" not in url, "bars endpoint must not be called when high is cached"
        return _FakeResponse({"latestTrade": {"p": 90.0}})

    monkeypatch.setattr(prices.requests, "get", _get)
    # _SESSION.get also points at the same stubbed function for safety.
    monkeypatch.setattr(prices._SESSION, "get", _get)
    q = prices._alpaca_quote("VOO", cached_high=120.0)
    assert q.week52_high == 120.0
    assert q.price == 90.0
    assert all("/snapshot" in u for u in requested)
