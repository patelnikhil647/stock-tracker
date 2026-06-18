"""End-to-end tests for monitor.run_cycle: the right notification per event,
once per day, across simulated calendar days."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stocktracker import monitor, prices
from stocktracker.config import Config, MarketHours, NtfyConfig, WatchEntry, Watchlist

TZ = "America/New_York"


def _config(tmp_path):
    return Config(
        threshold=0.15,
        ntfy=NtfyConfig(server="https://ntfy.sh", topic="test-topic"),
        market_hours=MarketHours(
            enabled=False, timezone=TZ, open="09:30", close="16:00", weekdays=[0, 1, 2, 3, 4]
        ),
        state_db=tmp_path / "state.db",
    )


@pytest.fixture
def watchlist():
    return Watchlist(entries=[WatchEntry(ticker="VOO")])


@pytest.fixture
def sent(monkeypatch):
    """Capture every notify.send call as a dict of its kwargs."""
    calls = []

    def _fake_send(ntfy, *, title, message, tags=None, priority=None):
        calls.append({"title": title, "message": message, "tags": tags})

    monkeypatch.setattr(monitor.notify, "send", _fake_send)
    return calls


def _set_quote(monkeypatch, price, high=100.0):
    def _fake_get_quote(ticker, cached_high=None):
        return prices.Quote(ticker=ticker, price=price, week52_high=high)

    monkeypatch.setattr(monitor.prices, "get_quote", _fake_get_quote)


def _set_day(monkeypatch, date_str):
    """Pin monitor's notion of 'today' (market-tz calendar date) to date_str."""
    fixed = datetime.fromisoformat(date_str + "T12:00:00").replace(tzinfo=ZoneInfo(TZ))

    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz is None else fixed.astimezone(tz)

    monkeypatch.setattr(monitor, "datetime", _FakeDateTime)


def test_alert_then_quiet_same_day(tmp_path, watchlist, sent, monkeypatch):
    cfg = _config(tmp_path)
    _set_day(monkeypatch, "2026-06-15")
    _set_quote(monkeypatch, price=84.0)  # 16% below high -> below threshold

    monitor.run_cycle(cfg, watchlist)
    assert len(sent) == 1
    assert "down 16.0%" in sent[0]["title"]

    # Re-check same day, still below -> no second push.
    monitor.run_cycle(cfg, watchlist)
    assert len(sent) == 1


def test_reminder_next_day(tmp_path, watchlist, sent, monkeypatch):
    cfg = _config(tmp_path)
    _set_quote(monkeypatch, price=84.0)

    _set_day(monkeypatch, "2026-06-15")
    monitor.run_cycle(cfg, watchlist)  # initial alert

    _set_day(monkeypatch, "2026-06-16")
    monitor.run_cycle(cfg, watchlist)  # daily reminder
    assert len(sent) == 2
    assert "still down" in sent[1]["title"]
    assert sent[1]["tags"] == "chart_with_downwards_trend"


def test_recovery_notifies_and_rearms(tmp_path, watchlist, sent, monkeypatch):
    cfg = _config(tmp_path)

    _set_day(monkeypatch, "2026-06-15")
    _set_quote(monkeypatch, price=84.0)
    monitor.run_cycle(cfg, watchlist)  # alert

    # Recovers above threshold -> recovery push (up tag), then re-arm.
    _set_quote(monkeypatch, price=95.0)
    monitor.run_cycle(cfg, watchlist)
    assert len(sent) == 2
    assert "recovered" in sent[1]["title"]
    assert sent[1]["tags"] == "chart_with_upwards_trend"

    # Still above -> quiet.
    monitor.run_cycle(cfg, watchlist)
    assert len(sent) == 2

    # Dips below again -> fresh alert.
    _set_quote(monkeypatch, price=80.0)
    monitor.run_cycle(cfg, watchlist)
    assert len(sent) == 3
    assert "down" in sent[2]["title"]
