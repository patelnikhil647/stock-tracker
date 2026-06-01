"""Load and validate config and watchlist files, and manage the watchlist.

Both ``config.yaml`` and ``watchlist.yaml`` are gitignored and created by
``stocktracker init`` (see templates.py), so the user's private ntfy topics never
enter git.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import yaml

# Project root = two levels up from this file (src/stocktracker/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Single gitignored config; created by `stocktracker init`.
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
WATCHLIST_PATH = PROJECT_ROOT / "watchlist.yaml"


@dataclass
class NtfyConfig:
    server: str
    topic: str
    priority: str = "high"
    # Private topic the tappable action buttons post to; the listener subscribes
    # to it. Optional until the listener feature (Milestone 3) is in use.
    command_topic: str = ""


@dataclass
class MarketHours:
    enabled: bool
    timezone: str
    open: str
    close: str
    weekdays: list[int]

    def is_open(self, now: Optional[datetime] = None) -> bool:
        """Return True if `now` falls within the configured market window."""
        if not self.enabled:
            return True
        tz = ZoneInfo(self.timezone)
        now = now.astimezone(tz) if now else datetime.now(tz)
        if now.weekday() not in self.weekdays:
            return False
        open_t = _parse_hhmm(self.open)
        close_t = _parse_hhmm(self.close)
        return open_t <= now.time() <= close_t


@dataclass
class Config:
    threshold: float
    ntfy: NtfyConfig
    market_hours: MarketHours
    state_db: Path


@dataclass
class WatchEntry:
    ticker: str
    threshold: Optional[float] = None  # per-ticker override of the global threshold


@dataclass
class Watchlist:
    entries: list[WatchEntry] = field(default_factory=list)

    @property
    def tickers(self) -> list[str]:
        return [e.ticker for e in self.entries]


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found — run `stocktracker init` to create it."
        )
    data = yaml.safe_load(path.read_text()) or {}

    threshold = float(data.get("threshold", 0.15))
    if not 0 <= threshold < 1:
        raise ValueError(f"threshold must be in [0, 1), got {threshold}")

    ntfy_data = data.get("ntfy") or {}
    # The topic is validated lazily (at send time, see notify.send) rather than
    # here, so read-only commands like `list`/`status` work before ntfy is set up.
    ntfy = NtfyConfig(
        server=ntfy_data.get("server", "https://ntfy.sh").rstrip("/"),
        topic=(ntfy_data.get("topic") or "").strip(),
        priority=ntfy_data.get("priority", "high"),
        command_topic=(ntfy_data.get("command_topic") or "").strip(),
    )

    mh = data.get("market_hours") or {}
    market_hours = MarketHours(
        enabled=bool(mh.get("enabled", True)),
        timezone=mh.get("timezone", "America/New_York"),
        open=mh.get("open", "09:30"),
        close=mh.get("close", "16:00"),
        weekdays=list(mh.get("weekdays", [0, 1, 2, 3, 4])),
    )

    state_db = Path(data.get("state_db", "data/state.db"))
    if not state_db.is_absolute():
        state_db = PROJECT_ROOT / state_db

    return Config(
        threshold=threshold,
        ntfy=ntfy,
        market_hours=market_hours,
        state_db=state_db,
    )


def load_watchlist(path: Path = WATCHLIST_PATH) -> Watchlist:
    if not path.exists():
        return Watchlist()
    data = yaml.safe_load(path.read_text()) or {}
    entries: list[WatchEntry] = []
    for raw in data.get("tickers", []) or []:
        if isinstance(raw, str):
            entries.append(WatchEntry(ticker=raw.strip().upper()))
        elif isinstance(raw, dict):
            entries.append(
                WatchEntry(
                    ticker=str(raw["ticker"]).strip().upper(),
                    threshold=(
                        float(raw["threshold"]) if raw.get("threshold") is not None else None
                    ),
                )
            )
    return Watchlist(entries=entries)


def save_watchlist(watchlist: Watchlist, path: Path = WATCHLIST_PATH) -> None:
    out: list = []
    for e in watchlist.entries:
        if e.threshold is None:
            out.append(e.ticker)
        else:
            out.append({"ticker": e.ticker, "threshold": e.threshold})
    path.write_text(yaml.safe_dump({"tickers": out}, sort_keys=False))


def add_ticker(ticker: str, path: Path = WATCHLIST_PATH) -> bool:
    """Add a ticker to the watchlist. Returns True if added, False if already present."""
    ticker = ticker.strip().upper()
    wl = load_watchlist(path)
    if ticker in wl.tickers:
        return False
    wl.entries.append(WatchEntry(ticker=ticker))
    save_watchlist(wl, path)
    return True


def remove_ticker(ticker: str, path: Path = WATCHLIST_PATH) -> bool:
    """Remove a ticker from the watchlist. Returns True if removed, False if absent."""
    ticker = ticker.strip().upper()
    wl = load_watchlist(path)
    before = len(wl.entries)
    wl.entries = [e for e in wl.entries if e.ticker != ticker]
    if len(wl.entries) == before:
        return False
    save_watchlist(wl, path)
    return True
