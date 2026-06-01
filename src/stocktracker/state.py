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
        self._conn.execute(_SCHEMA)
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
        self._conn.execute("DELETE FROM ticker_state WHERE ticker = ?", (ticker.upper(),))
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
