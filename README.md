# stock-tracker

A personal ETF drop-alert tool. It checks your watchlist of ETFs and pushes a
notification to your phone (via [ntfy](https://ntfy.sh/)) whenever one falls more
than a configured percentage (default **15%**) below its 52-week high.

- **Data:** [Alpaca](https://alpaca.markets/) market data (set an API key — see
  [Price data](#price-data)), with [`yfinance`](https://pypi.org/project/yfinance/)
  as an automatic fallback when no key is set.
- **Alerts:** ntfy — free, open-source push notifications.
- **Cadence:** one alert when an ETF first drops past the threshold, then a
  **daily reminder** for each later day it stays below (at most one per calendar
  day, market timezone), and a **recovery notification** when it climbs back above
  the threshold — after which it re-arms for the next crossing.

> Single-user, run-it-on-your-own-laptop tool. No Charles Schwab integration yet
> (see [Roadmap](#roadmap)).

## Setup

### 1. Install

```bash
cd stock-tracker
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"
```
> Note: Editable install needs pip >= 21.3 (PEP 660)

### 2. Initialize your config

```bash
.venv/bin/stocktracker init
```

This creates a **gitignored** `config.yaml` (with a random private ntfy topic like
`mango-eye-llama`) and a `watchlist.yaml` seeded with `VOO`. Neither file is
committed to git, so your private topic stays out of version control. It prints the
generated topic — note it for the next step.

### 3. Set up phone notifications

1. Install the **ntfy** app on your Pixel (Google Play or F-Droid).
2. **Subscribe to topic** and enter the alert topic that `init` printed (it's also
   in `config.yaml` under `ntfy.topic`).
3. Confirm it works:

   ```bash
   .venv/bin/stocktracker test-notify
   ```

   You should get a notification on your phone within a second or two.

### 4. Build your watchlist

```bash
.venv/bin/stocktracker add VOO SCHD NVDA   # add several at once; each is validated
.venv/bin/stocktracker remove NVDA
.venv/bin/stocktracker list
.venv/bin/stocktracker status     # live prices, 52-wk highs, drop %, alert state
```

## Usage

| Command | What it does |
|---------|--------------|
| `stocktracker init` | Create `config.yaml` (random topic) + `watchlist.yaml`. `--force` overwrites. |
| `stocktracker check` | Run one monitoring cycle (sends alerts). This is what the scheduler calls. |
| `stocktracker add <TICKER>...` | Add one or more ETFs; each symbol is validated, unresolved ones are skipped with a warning. |
| `stocktracker remove <TICKER>...` | Remove one or more ETFs; ones not on the watchlist are skipped with a warning. |
| `stocktracker list` | Show watched tickers and their thresholds. |
| `stocktracker status` | Show current price, 52-wk high, drop %, and state per ticker. |
| `stocktracker test-notify` | Send a test notification to your phone. |

`check` is a **no-op outside US market hours** (configurable in your config), so
running it on a frequent schedule is safe. To force a one-off run when the market
is closed (e.g. for testing), pass `-i` / `--ignore-market-hours`:

```bash
.venv/bin/stocktracker check --ignore-market-hours
```

To always run regardless of the clock, set `market_hours.enabled: false` instead.

## Keeping your topic private

Your ntfy topic is effectively a password, so it must stay out of git. Both
`config.yaml` and `watchlist.yaml` are **gitignored** and created by
`stocktracker init` — there is no committed config, so your private topic never
reaches GitHub. The default config/watchlist templates live inside the package
(`src/stocktracker/templates.py`), and `init` fills in a freshly generated random
topic for you.

## Configuration keys

- `threshold` — fractional drop that triggers an alert (`0.15` = 15%).
- `ntfy.server` / `ntfy.topic` / `ntfy.priority` — where alerts go.
- `ntfy.command_topic` — private topic for the (Phase 2+) tappable action buttons.
- `market_hours` — when `check` actually runs.
- `state_db` — path to the SQLite file that remembers alert state (gitignored).

Per-ticker threshold overrides live in `watchlist.yaml`:

```yaml
tickers:
  - VOO
  - ticker: SCHD
    threshold: 0.10   # alert SCHD at 10% instead of the global 15%
```

## Price data

Prices and 52-week highs come from **Alpaca** when an API key is configured, and
fall back to **yfinance** automatically when it isn't (so the tool still works
with zero setup). Get free API keys from your
[Alpaca dashboard](https://app.alpaca.markets/).

**Option 1 — `.env` file** (simplest for local use): create a `.env` file at the
project root (it's already gitignored):

```
APCA_API_KEY_ID=your-key-id
APCA_API_SECRET_KEY=your-secret-key
```

`stocktracker` loads this file automatically on every run.

**Option 2 — shell environment**: export the variables before running:

```bash
export APCA_API_KEY_ID="your-key-id"
export APCA_API_SECRET_KEY="your-secret-key"
```

The free Alpaca data tier uses the **IEX** feed, which is the default. If you have
a paid SIP subscription, set `ALPACA_DATA_FEED=sip`. (Alpaca has no native
52-week-high field, so it's computed from ~1 year of daily bars.)

The `.env` file works for scheduled jobs too — launchd and cron both invoke
`stocktracker` directly, which loads `.env` at startup the same way a shell
invocation does. With no `.env` and no keys in the environment, every quote
silently uses yfinance.

## Running it 24/7

Pick **one** scheduler. Both fire on the wall clock at **:00 and :30** each hour
(not relative to when the machine wakes). launchd runs all day; cron is restricted
to market hours (Mon–Fri 6am–1pm). Either way the market-hours guard keeps any
off-hours runs cheap and silent — which is why the all-day launchd schedule is fine.

> ⚠️ **macOS: don't keep the project in `~/Documents`, `~/Desktop`, or
> `~/Downloads`.** Those folders are protected by macOS privacy (TCC), and
> `cron`/`launchd` jobs are denied access to them — the job fails before it starts
> with `PermissionError: [Errno 1] Operation not permitted` (you'll see it loaded
> but with no PID in `launchctl list`). Put the checkout somewhere unprotected like
> `~/dev/stock-tracker`. If you must keep it in a protected folder, grant **Full
> Disk Access** (System Settings → Privacy & Security → Full Disk Access) to the
> venv's Python interpreter — but relocating is simpler and more reliable. The venv
> hardcodes paths, so after moving the project, recreate it:
> `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`.

The examples below use `/Users/username/path/to/stock-tracker` — replace it with your actual
(unprotected) checkout path.

### Option A — cron

```bash
crontab -e
```

```cron
*/30 6-13 * * 1-5 /Users/username/path/to/stock-tracker/.venv/bin/stocktracker check >> /Users/username/path/to/stock-tracker/data/cron.log 2>&1
```

This runs Mon–Fri at :00 and :30 from 06:00 through 13:30 (local time) — your usual
market window. (The window ends at 13:30 rather than exactly 13:00 to keep the minute
field a clean `*/30`; the extra 13:30 run is a harmless no-op.) cron fires on the wall
clock and **skips** runs that fall while the machine is asleep — it does not catch them
up on wake — so it already behaves the way you want.

(macOS note: `cron` is subject to the same protected-folder rule; if you keep the
project under a protected folder you must grant Full Disk Access to `/usr/sbin/cron`.)

### Option B — macOS launchd (survives reboots cleanly)

Create `~/Library/LaunchAgents/com.stocktracker.check.plist` (launchd requires
absolute paths — `~` is not expanded):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.stocktracker.check</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/username/path/to/stock-tracker/.venv/bin/stocktracker</string>
        <string>check</string>
    </array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Minute</key><integer>0</integer></dict>
        <dict><key>Minute</key><integer>30</integer></dict>
    </array>
    <key>StandardOutPath</key>
    <string>/Users/username/path/to/stock-tracker/data/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/username/path/to/stock-tracker/data/launchd.log</string>
</dict>
</plist>
```

`StartCalendarInterval` fires on the wall clock — at :00 and :30 of every hour
(wake at 9:15 → next run 9:30, then 10:00, …), unlike `StartInterval`, which counts
a fixed number of seconds from when the job loaded/woke. Runs scheduled while the
machine is asleep are skipped, **except** launchd runs a single catch-up on wake if a
boundary was missed (wake at 9:45 → the 9:30 run fires once immediately, then 10:00).
That catch-up is harmless — `check` is a no-op outside market hours and alerts at most
once per ticker per day. The schedule runs all day; the market-hours guard handles
off-hours, so there's no need to encode a time window in the plist.

Then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.stocktracker.check.plist
# To stop: launchctl unload ~/Library/LaunchAgents/com.stocktracker.check.plist
```

If `launchctl list | grep stock` shows the job loaded but with no PID and a non-zero
exit, check `data/launchd.log` — a `PermissionError ... Operation not permitted`
there is the protected-folder issue above.

## Tests

```bash
.venv/bin/pytest
```

## Roadmap

### Phase 1 — MVP 
- Watchlist monitoring, once-per-crossing alerts, ntfy push, scheduling.
- **`check --ignore-market-hours` (`-i`):** force a one-off cycle when the market
  is closed, for manual testing.

### Phase 2 — Setup, batch management, and daily reminders (current)
- ✅ **Batch `add`/`remove`:** accept many tickers in one command. `add` validates
  each symbol via the price provider and skips unresolved ones with a warning; `remove` warns
  on tickers not present and cleans up their stored state.
- ✅ **`stocktracker init` bootstrap:** one command creates a gitignored
  `config.yaml` (with a freshly generated random topic) and a `watchlist.yaml`
  seeded with `VOO` — so you never have to invent a topic or risk committing it.
- ✅ **Daily reminders + recovery notification:** while an ETF stays below the
  threshold, send one reminder per calendar day; when it climbs back above the
  threshold, send a recovery notification and re-arm.
- **Tappable suppress** (next): a **Suppress** action button on the reminder to
  silence it while still below threshold. The button posts to a private
  `command_topic`, and a long-running `stocktracker listen` service
  (outbound-only, no inbound exposure) applies the suppress. The `SUPPRESSED`
  state is already scaffolded for this.

### Phase 3 — Charles Schwab integration
- Auto-import your real holdings (so the watchlist self-populates) and reply to an
  alert to buy more. Note Schwab's refresh token expires every ~7 days, requiring a
  periodic manual re-login.
- **Interactive alerts:** ntfy action buttons ("Buy $X more of VOO?") that the
  laptop listens for via an ntfy command topic.

### Phase 4 — Nice to have (after the phases above)
- **ntfy authentication:** move beyond a secret-topic-only model by supporting ntfy
  access tokens (Bearer) or basic auth, so even a known topic can't be read or
  flooded by others. Only enforceable on a self-hosted ntfy server or ntfy.sh Pro
  (free public topics have no access control).
- **Dry-run mode (`check --dry-run`):** evaluate and log what would alert, without
  sending notifications.
- **Recovery notifications:** a "good news" ping when an ETF climbs back above the
  threshold (reuses the existing `ARMED` re-arm transition).
- **Heartbeat / health-check:** a periodic "monitor is alive" notification so a
  silently dead cron/launchd job is detectable.
- **Alert history (`stocktracker history`):** review past alerts from the state
  DB's `last_alert_ts`.
- **Resilience & ergonomics:** yfinance retry/backoff; manage per-ticker thresholds
  from the CLI (currently YAML-only).
