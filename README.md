# stock-tracker

A personal ETF drop-alert tool. It checks your watchlist of ETFs and pushes a
notification to your phone (via [ntfy](https://ntfy.sh/)) whenever one falls more
than a configured percentage (default **15%**) below its 52-week high.

- **Data:** [`yfinance`](https://pypi.org/project/yfinance/) — free, no API key.
- **Alerts:** ntfy — free, open-source push notifications.
- **Cadence (MVP):** alerts **once per crossing**. Once an ETF drops past the
  threshold you get one alert; you won't get another until it recovers above the
  threshold and crosses back down.

> Single-user, run-it-on-your-own-laptop tool. No Charles Schwab integration yet
> (see [Roadmap](#roadmap)).

## Setup

### 1. Install

```bash
cd stock-tracker
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### 2. Set up phone notifications

1. Install the **ntfy** app on your Pixel (Google Play or F-Droid).
2. Pick a private, hard-to-guess topic name (treat it like a password — on the
   public `ntfy.sh` server anyone who knows the topic can read your alerts).
3. Create your private config and set the topic in it (see
   [Keeping your topic private](#keeping-your-topic-private)):

   ```bash
   cp config.example.yaml config.local.yaml
   # then edit config.local.yaml and set ntfy.topic to your private name
   ```
4. In the app, **Subscribe to topic** and enter the same name.
5. Confirm it works:

   ```bash
   .venv/bin/stocktracker test-notify
   ```

   You should get a notification on your phone within a second or two.

### 3. Build your watchlist

```bash
.venv/bin/stocktracker add VOO
.venv/bin/stocktracker add SCHD
.venv/bin/stocktracker list
.venv/bin/stocktracker status     # live prices, 52-wk highs, drop %, alert state
```

## Usage

| Command | What it does |
|---------|--------------|
| `stocktracker check` | Run one monitoring cycle (sends alerts). This is what the scheduler calls. |
| `stocktracker add <TICKER>` | Add an ETF to the watchlist. |
| `stocktracker remove <TICKER>` | Remove an ETF. |
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

Your ntfy topic is effectively a password, so it must stay out of git. Config is
layered:

- **`config.example.yaml`** — committed template with defaults and a placeholder
  topic. Safe to push to GitHub. (The placeholder is rejected at runtime so you
  can't accidentally use it.)
- **`config.local.yaml`** — your real config, **gitignored** so it never reaches
  GitHub. Create it once:

  ```bash
  cp config.example.yaml config.local.yaml
  # edit config.local.yaml -> set ntfy.topic to your private topic
  ```

At load time, `config.local.yaml` is **deep-merged over** `config.example.yaml`:
every key you set locally wins (recursively), and anything you leave out falls back
to the example. So `config.local.yaml` can be a full copy or hold just the keys you
want to override (e.g. only `ntfy.topic`).

## Configuration keys

- `threshold` — fractional drop that triggers an alert (`0.15` = 15%).
- `ntfy.server` / `ntfy.topic` / `ntfy.priority` — where alerts go.
- `market_hours` — when `check` actually runs.
- `state_db` — path to the SQLite file that remembers alert state (gitignored).

Per-ticker threshold overrides live in `watchlist.yaml`:

```yaml
tickers:
  - VOO
  - ticker: SCHD
    threshold: 0.10   # alert SCHD at 10% instead of the global 15%
```

## Running it 24/7

Pick **one** scheduler. Both call `check` every 30 minutes; the market-hours guard
keeps off-hours runs cheap and silent.

### Option A — cron

```bash
crontab -e
```

Add (adjust the path to your checkout):

```cron
*/30 * * * * /Users/nikhil.patel/Documents/Development/personal/stock-tracker/.venv/bin/stocktracker check >> /Users/nikhil.patel/Documents/Development/personal/stock-tracker/data/cron.log 2>&1
```

### Option B — macOS launchd (survives reboots cleanly)

Create `~/Library/LaunchAgents/com.stocktracker.check.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.stocktracker.check</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/nikhil.patel/Documents/Development/personal/stock-tracker/.venv/bin/stocktracker</string>
        <string>check</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardOutPath</key>
    <string>/Users/nikhil.patel/Documents/Development/personal/stock-tracker/data/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/nikhil.patel/Documents/Development/personal/stock-tracker/data/launchd.log</string>
</dict>
</plist>
```

Then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.stocktracker.check.plist
# To stop: launchctl unload ~/Library/LaunchAgents/com.stocktracker.check.plist
```

## Tests

```bash
.venv/bin/pytest
```

## Roadmap

### Phase 1 — MVP (current)
- Watchlist monitoring, once-per-crossing alerts, ntfy push, scheduling.
- **`check --ignore-market-hours` (`-i`):** force a one-off cycle when the market
  is closed, for manual testing.

### Phase 2 — Hardening, setup, and updated notifications
- **ntfy authentication:** move beyond a secret-topic-only model by supporting ntfy
  access tokens (Bearer) or basic auth, so even a known topic can't be read or
  flooded by others. Adds optional `ntfy.token` (or `ntfy.user` + `ntfy.password`)
  to config and an `Authorization` header in `notify.send`.
- **`stocktracker init` bootstrap:** one command that copies `config.example.yaml`
  to `config.local.yaml` and fills `ntfy.topic` with a freshly generated random
  topic name — so you never have to invent one or risk committing it. Also adds
  a sample watchlist.yaml file to replace the current watchlist.yaml that is git
  tracked.
- **Daily reminders:** while an ETF stays below the threshold, send a daily
  reminder until you tap "suppress"; resume only after it recovers and re-crosses.
  The state machine already has the `SUPPRESSED` state scaffolded for this.
- **Batch `add` with validation:** accept many tickers in one command
  (`stocktracker add VOO SCHD NVDA`). For each argument, check the symbol exists
  (resolves via yfinance); if it does, add it to the watchlist, otherwise print a
  warning naming that ticker and continue to the next argument. Catches typos
  immediately instead of failing silently every cycle.
- **Batch `remove`:** accept many tickers in one command
  (`stocktracker remove VOO SCHD NVDA`). For each argument, remove it from the
  watchlist; if it isn't on the watchlist, print a warning naming that ticker and
  continue to the next argument.

### Phase 3 — Charles Schwab integration
- Auto-import your real holdings (so the watchlist self-populates) and reply to an
  alert to buy more. Note Schwab's refresh token expires every ~7 days, requiring a
  periodic manual re-login.
- **Interactive alerts:** ntfy action buttons ("Buy $X more of VOO?") that the
  laptop listens for via an ntfy command topic.

### Phase 4 — Nice to have (after the phases above)
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
