import pytest

from stocktracker.state import (
    ARMED,
    EVENT_ALERT,
    EVENT_NONE,
    EVENT_RECOVERED,
    EVENT_REMINDER,
    TRIGGERED,
    StateStore,
)

DAY1 = "2026-06-15"
DAY2 = "2026-06-16"
DAY3 = "2026-06-17"


@pytest.fixture
def store(tmp_path):
    s = StateStore(tmp_path / "state.db")
    yield s
    s.close()


def test_new_ticker_starts_armed(store):
    assert store.get("VOO").state == ARMED


def test_crossing_below_alerts_once_per_day(store):
    # First time below threshold -> alert.
    assert store.evaluate("VOO", drop_pct=0.16, threshold=0.15, today=DAY1) == EVENT_ALERT
    assert store.get("VOO").state == TRIGGERED
    # Still below later the same day -> no re-notification.
    assert store.evaluate("VOO", drop_pct=0.20, threshold=0.15, today=DAY1) == EVENT_NONE
    assert store.get("VOO").state == TRIGGERED


def test_still_below_next_day_sends_reminder(store):
    assert store.evaluate("VOO", drop_pct=0.16, threshold=0.15, today=DAY1) == EVENT_ALERT
    # New calendar day, still below -> one reminder.
    assert store.evaluate("VOO", drop_pct=0.18, threshold=0.15, today=DAY2) == EVENT_REMINDER
    # Same day again -> quiet.
    assert store.evaluate("VOO", drop_pct=0.18, threshold=0.15, today=DAY2) == EVENT_NONE
    # Yet another day -> reminder again.
    assert store.evaluate("VOO", drop_pct=0.18, threshold=0.15, today=DAY3) == EVENT_REMINDER


def test_no_alert_when_above_threshold(store):
    assert store.evaluate("VOO", drop_pct=0.05, threshold=0.15, today=DAY1) == EVENT_NONE
    assert store.get("VOO").state == ARMED


def test_recovery_notifies_then_rearms(store):
    assert store.evaluate("VOO", drop_pct=0.16, threshold=0.15, today=DAY1) == EVENT_ALERT
    # Recovers above the threshold -> recovery notification + re-arm.
    assert store.evaluate("VOO", drop_pct=0.10, threshold=0.15, today=DAY1) == EVENT_RECOVERED
    assert store.get("VOO").state == ARMED
    # Already armed and still above -> quiet.
    assert store.evaluate("VOO", drop_pct=0.08, threshold=0.15, today=DAY2) == EVENT_NONE
    # Crosses below again -> alerts again.
    assert store.evaluate("VOO", drop_pct=0.18, threshold=0.15, today=DAY2) == EVENT_ALERT
    assert store.get("VOO").state == TRIGGERED


def test_recovery_clears_notify_date_so_resdip_alerts_same_day(store):
    store.evaluate("VOO", drop_pct=0.16, threshold=0.15, today=DAY1)
    store.evaluate("VOO", drop_pct=0.10, threshold=0.15, today=DAY1)  # recovered
    # Re-dip the same day is a fresh crossing -> alert (not gated by the day lock).
    assert store.evaluate("VOO", drop_pct=0.16, threshold=0.15, today=DAY1) == EVENT_ALERT


def test_exactly_at_threshold_triggers(store):
    # drop_pct == threshold counts as "more than 15% below" boundary inclusive.
    assert store.evaluate("VOO", drop_pct=0.15, threshold=0.15, today=DAY1) == EVENT_ALERT


def test_last_drop_pct_persisted(store):
    store.evaluate("SCHD", drop_pct=0.12, threshold=0.15, today=DAY1)
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
