from stocktracker.prices import Quote


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
