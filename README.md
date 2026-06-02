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

## Running it 24/7

Pick **one** scheduler. Both call `check` every 30 minutes; the market-hours guard
keeps off-hours runs cheap and silent.

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
*/30 * * * * /Users/username/path/to/stock-tracker/.venv/bin/stocktracker check >> /Users/username/path/to/stock-tracker/data/cron.log 2>&1
```

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
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardOutPath</key>
    <string>/Users/username/path/to/stock-tracker/data/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/username/path/to/stock-tracker/data/launchd.log</string>
</dict>
</plist>
```

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

### Phase 1 — MVP (current)
- Watchlist monitoring, once-per-crossing alerts, ntfy push, scheduling.
- **`check --ignore-market-hours` (`-i`):** force a one-off cycle when the market
  is closed, for manual testing.

### Phase 2 — Setup, batch management, and daily reminders
- ✅ **Batch `add`/`remove`:** accept many tickers in one command. `add` validates
  each symbol via yfinance and skips unresolved ones with a warning; `remove` warns
  on tickers not present and cleans up their stored state.
- ✅ **`stocktracker init` bootstrap:** one command creates a gitignored
  `config.yaml` (with a freshly generated random topic) and a `watchlist.yaml`
  seeded with `VOO` — so you never have to invent a topic or risk committing it.
- **Daily reminders + tappable suppress** (next): while an ETF stays below the
  threshold, send a daily reminder until you tap a **Suppress** action button on
  the notification; resume only after it recovers above threshold and re-crosses.
  The button posts to a private `command_topic`, and a long-running
  `stocktracker listen` service (outbound-only, no inbound exposure) applies the
  suppress. The `SUPPRESSED` state is already scaffolded for this.

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
