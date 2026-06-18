"""SQLite-backed alert state machine.

States:
  ARMED      - drop < threshold (or never triggered). Ready to fire on a crossing.
  TRIGGERED  - drop >= threshold; an alert has already fired.
  SUPPRESSED - (future) user silenced daily reminders while still below threshold.

`evaluate` returns one of the EVENT_* constants telling the caller what (if any)
notification to send for one observation:
  ARMED + below threshold              -> TRIGGERED, EVENT_ALERT
  TRIGGERED + below on a new day       -> stay TRIGGERED, EVENT_REMINDER
  TRIGGERED + below, already notified   -> stay TRIGGERED, EVENT_NONE
  TRIGGERED + recovered above threshold -> ARMED, EVENT_RECOVERED
  ARMED + above threshold              -> stay ARMED, EVENT_NONE

"Once per day" uses a calendar-date string (`today`) the caller supplies in the
market timezone, stored in `last_notify_date`. The SUPPRESSED state stays
scaffolded for a future tappable-suppress feature and is not yet exercised.
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

# Notification events returned by `evaluate`.
EVENT_NONE = "NONE"
EVENT_ALERT = "ALERT"
EVENT_REMINDER = "REMINDER"
EVENT_RECOVERED = "RECOVERED"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticker_state (
    ticker          TEXT PRIMARY KEY,
    state           TEXT NOT NULL DEFAULT 'ARMED',
    last_alert_ts   TEXT,
    last_drop_pct   REAL,
    last_notify_date TEXT,
    updated_at      TEXT NOT NULL
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
    last_notify_date: str | None
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
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns missing from DBs created by older schema versions.

        `CREATE TABLE IF NOT EXISTS` never alters an existing table, so a live DB
        from before `last_notify_date` was added would lack the column.
        """
        cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(ticker_state)")}
        if "last_notify_date" not in cols:
            self._conn.execute("ALTER TABLE ticker_state ADD COLUMN last_notify_date TEXT")

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
            return TickerState(ticker, ARMED, None, None, None, _utcnow())
        return TickerState(
            ticker=row["ticker"],
            state=row["state"],
            last_alert_ts=row["last_alert_ts"],
            last_drop_pct=row["last_drop_pct"],
            last_notify_date=row["last_notify_date"],
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
            INSERT INTO ticker_state
                (ticker, state, last_alert_ts, last_drop_pct, last_notify_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                state=excluded.state,
                last_alert_ts=excluded.last_alert_ts,
                last_drop_pct=excluded.last_drop_pct,
                last_notify_date=excluded.last_notify_date,
                updated_at=excluded.updated_at
            """,
            (
                st.ticker,
                st.state,
                st.last_alert_ts,
                st.last_drop_pct,
                st.last_notify_date,
                st.updated_at,
            ),
        )
        self._conn.commit()

    def evaluate(self, ticker: str, drop_pct: float, threshold: float, today: str) -> str:
        """Apply the state machine for one observation; return an EVENT_* constant.

        `today` is a calendar-date string (market timezone) used to enforce the
        "one notification per day" rule while a ticker stays below the threshold.
        Persists the new state either way.
        """
        ticker = ticker.upper()
        current = self.get(ticker)
        below = drop_pct >= threshold
        new_state = current.state
        last_alert_ts = current.last_alert_ts
        last_notify_date = current.last_notify_date
        event = EVENT_NONE

        if below:
            if current.state == ARMED:
                # Fresh crossing: alert and start the per-day reminder clock.
                new_state = TRIGGERED
                event = EVENT_ALERT
                last_alert_ts = _utcnow()
                last_notify_date = today
            elif last_notify_date != today:
                # Still below on a new day: send the daily reminder.
                event = EVENT_REMINDER
                last_alert_ts = _utcnow()
                last_notify_date = today
            # else: already notified today -> stay quiet.
        else:
            if current.state == TRIGGERED:
                # Recovered above the threshold: notify once, then re-arm.
                event = EVENT_RECOVERED
            new_state = ARMED
            last_notify_date = None

        self._upsert(
            TickerState(
                ticker=ticker,
                state=new_state,
                last_alert_ts=last_alert_ts,
                last_drop_pct=drop_pct,
                last_notify_date=last_notify_date,
                updated_at=_utcnow(),
            )
        )
        return event
