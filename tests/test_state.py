import pytest

from stocktracker.state import ARMED, TRIGGERED, StateStore


@pytest.fixture
def store(tmp_path):
    s = StateStore(tmp_path / "state.db")
    yield s
    s.close()


def test_new_ticker_starts_armed(store):
    assert store.get("VOO").state == ARMED


def test_crossing_below_alerts_once(store):
    # First time below threshold -> alert.
    assert store.evaluate("VOO", drop_pct=0.16, threshold=0.15) is True
    assert store.get("VOO").state == TRIGGERED
    # Still below on the next cycle -> no re-alert (once per crossing).
    assert store.evaluate("VOO", drop_pct=0.20, threshold=0.15) is False
    assert store.get("VOO").state == TRIGGERED


def test_no_alert_when_above_threshold(store):
    assert store.evaluate("VOO", drop_pct=0.05, threshold=0.15) is False
    assert store.get("VOO").state == ARMED


def test_recovery_rearms_and_recrossing_alerts_again(store):
    assert store.evaluate("VOO", drop_pct=0.16, threshold=0.15) is True
    # Recovers above the threshold -> re-arm, silently.
    assert store.evaluate("VOO", drop_pct=0.10, threshold=0.15) is False
    assert store.get("VOO").state == ARMED
    # Crosses below again -> alerts again.
    assert store.evaluate("VOO", drop_pct=0.18, threshold=0.15) is True
    assert store.get("VOO").state == TRIGGERED


def test_exactly_at_threshold_triggers(store):
    # drop_pct == threshold counts as "more than 15% below" boundary inclusive.
    assert store.evaluate("VOO", drop_pct=0.15, threshold=0.15) is True


def test_last_drop_pct_persisted(store):
    store.evaluate("SCHD", drop_pct=0.12, threshold=0.15)
    assert store.get("SCHD").last_drop_pct == pytest.approx(0.12)


# --- 52-week high cache ------------------------------------------------------


def test_cached_high_miss_when_absent(store):
    assert store.get_cached_high("VOO", "2026-06-13") is None


def test_cached_high_round_trip_same_day(store):
    store.set_cached_high("VOO", 123.45, "2026-06-13")
    assert store.get_cached_high("VOO", "2026-06-13") == pytest.approx(123.45)


def test_cached_high_miss_on_different_day(store):
    store.set_cached_high("VOO", 123.45, "2026-06-12")
    assert store.get_cached_high("VOO", "2026-06-13") is None


def test_cached_high_upsert_overwrites(store):
    store.set_cached_high("VOO", 100.0, "2026-06-13")
    store.set_cached_high("VOO", 150.0, "2026-06-13")
    assert store.get_cached_high("VOO", "2026-06-13") == pytest.approx(150.0)


def test_delete_clears_cached_high(store):
    store.set_cached_high("VOO", 100.0, "2026-06-13")
    store.delete("VOO")
    assert store.get_cached_high("VOO", "2026-06-13") is None
