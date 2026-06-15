"""SQLite-backed alert state machine.

States:
  ARMED      - drop < threshold (or never triggered). Ready to fire on a crossing.
  TRIGGERED  - drop >= threshold; an alert has already fired.
  SUPPRESSED - (phase 2) user silenced daily reminders while still below threshold.

MVP transitions:
  ARMED -> TRIGGERED   when drop crosses >= threshold  => caller sends an alert
  TRIGGERED -> ARMED   when drop recovers < threshold  => silent re-arm

The SUPPRESSED state and daily-reminder logic are scaffolded for phase 2 but are
not exercised by the MVP monitor.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ARMED = "ARMED"
TRIGGERED = "TRIGGERED"
SUPPRESSED = "SUPPRESSED"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticker_state (
    ticker        TEXT PRIMARY KEY,
    state         TEXT NOT NULL DEFAULT 'ARMED',
    last_alert_ts TEXT,
    last_drop_pct REAL,
    updated_at    TEXT NOT NULL
);

-- Caches the 52-week high (which only changes once per day) so the recurring
-- `check` cycle can skip refetching a year of daily bars from the price API.
CREATE TABLE IF NOT EXISTS high_cache (
    ticker      TEXT PRIMARY KEY,
    week52_high REAL NOT NULL,
    as_of_date  TEXT NOT NULL
);
"""


@dataclass
class TickerState:
    ticker: str
    state: str
    last_alert_ts: str | None
    last_drop_pct: float | None
    updated_at: str


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get(self, ticker: str) -> TickerState:
        ticker = ticker.upper()
        row = self._conn.execute(
            "SELECT * FROM ticker_state WHERE ticker = ?", (ticker,)
        ).fetchone()
        if row is None:
            return TickerState(ticker, ARMED, None, None, _utcnow())
        return TickerState(
            ticker=row["ticker"],
            state=row["state"],
            last_alert_ts=row["last_alert_ts"],
            last_drop_pct=row["last_drop_pct"],
            updated_at=row["updated_at"],
        )

    def delete(self, ticker: str) -> None:
        """Remove a ticker's stored state (e.g. when it leaves the watchlist)."""
        ticker = ticker.upper()
        self._conn.execute("DELETE FROM ticker_state WHERE ticker = ?", (ticker,))
        self._conn.execute("DELETE FROM high_cache WHERE ticker = ?", (ticker,))
        self._conn.commit()

    def get_cached_high(self, ticker: str, today: str) -> Optional[float]:
        """Return the cached 52-week high for `ticker` if it was stored on `today`.

        `today` is a calendar-date string (the caller decides the timezone). A
        miss — no row, or a row from an earlier day — returns None so the caller
        refetches and re-caches.
        """
        row = self._conn.execute(
            "SELECT week52_high, as_of_date FROM high_cache WHERE ticker = ?",
            (ticker.upper(),),
        ).fetchone()
        if row is None or row["as_of_date"] != today:
            return None
        return float(row["week52_high"])

    def set_cached_high(self, ticker: str, high: float, today: str) -> None:
        """Upsert the cached 52-week high for `ticker`, stamped with `today`."""
        self._conn.execute(
            """
            INSERT INTO high_cache (ticker, week52_high, as_of_date)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                week52_high=excluded.week52_high,
                as_of_date=excluded.as_of_date
            """,
            (ticker.upper(), float(high), today),
        )
        self._conn.commit()

    def _upsert(self, st: TickerState) -> None:
        self._conn.execute(
            """
            INSERT INTO ticker_state (ticker, state, last_alert_ts, last_drop_pct, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                state=excluded.state,
                last_alert_ts=excluded.last_alert_ts,
                last_drop_pct=excluded.last_drop_pct,
                updated_at=excluded.updated_at
            """,
            (st.ticker, st.state, st.last_alert_ts, st.last_drop_pct, st.updated_at),
        )
        self._conn.commit()

    def evaluate(self, ticker: str, drop_pct: float, threshold: float) -> bool:
        """Apply the MVP state machine for one observation.

        Returns True if the caller should send an alert (i.e. an ARMED ticker
        just crossed at/above the threshold). Persists the new state either way.
        """
        ticker = ticker.upper()
        current = self.get(ticker)
        below = drop_pct >= threshold
        should_alert = False
        new_state = current.state
        last_alert_ts = current.last_alert_ts

        if below:
            if current.state == ARMED:
                new_state = TRIGGERED
                should_alert = True
                last_alert_ts = _utcnow()
            # TRIGGERED / SUPPRESSED while still below: stay put (MVP: no re-alert).
        else:
            # Recovered above the threshold: re-arm so the next crossing alerts.
            new_state = ARMED

        self._upsert(
            TickerState(
                ticker=ticker,
                state=new_state,
                last_alert_ts=last_alert_ts,
                last_drop_pct=drop_pct,
                updated_at=_utcnow(),
            )
        )
        return should_alert
