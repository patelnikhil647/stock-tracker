"""In-package templates and helpers used by `stocktracker init`.

The default config/watchlist live here (not as committed root files) so that the
only config the user ever sees is the single gitignored ``config.yaml`` that
``init`` writes.
"""

from __future__ import annotations

import secrets

# Short, friendly nouns (all <= 6 letters) for generating readable topic names
# like "mango-eye-llama". Kept simple and family-friendly.
_TOPIC_WORDS = [
    "mango", "llama", "eye", "tiger", "otter", "panda", "robin", "maple",
    "cocoa", "lemon", "olive", "river", "stone", "cloud", "ember", "fox",
    "owl", "bear", "wolf", "hawk", "crab", "moth", "newt", "seal",
    "toad", "wren", "bison", "koala", "gecko", "viper", "lotus", "fern",
    "cedar", "birch", "aspen", "reed", "moss", "kelp", "coral", "pearl",
    "amber", "onyx", "jade", "ruby", "opal", "slate", "comet", "nova",
    "orbit", "delta", "piano", "cello", "drum", "flute", "banjo", "puma",
]

# Render placeholders (avoids str.format brace pitfalls with YAML).
_ALERT = "__ALERT_TOPIC__"
_COMMAND = "__COMMAND_TOPIC__"

DEFAULT_CONFIG = """\
# stock-tracker configuration
#
# Created by `stocktracker init`. This file is gitignored — it holds your private
# ntfy topics, so it stays out of version control.

# Fraction below the 52-week high that triggers an alert. 0.15 = 15%.
threshold: 0.15

ntfy:
  # Public ntfy server. You can self-host and change this if you prefer.
  server: "https://ntfy.sh"
  # Your private alert topic (treat it like a password). Subscribe to THIS topic
  # in the ntfy app on your phone to receive alerts.
  topic: "__ALERT_TOPIC__"
  # Private command topic for the tappable action buttons. The laptop listener
  # subscribes to this; you do NOT subscribe to it on your phone.
  command_topic: "__COMMAND_TOPIC__"
  # Notification priority: min, low, default, high, urgent.
  priority: "high"

# Only run `check` during US market hours. It is a no-op outside this window;
# pass -i/--ignore-market-hours to force a run.
market_hours:
  enabled: true
  timezone: "America/New_York"
  open: "09:30"
  close: "16:00"
  # 0 = Monday ... 6 = Sunday
  weekdays: [0, 1, 2, 3, 4]

# Where the SQLite alert-state database lives (relative to project root).
state_db: "data/state.db"
"""

DEFAULT_WATCHLIST = """\
# ETFs to monitor. Manage with the CLI:
#   stocktracker add VOO SCHD
#   stocktracker remove VOO
#   stocktracker list
#
# Optionally override the global threshold per-ticker:
#   - ticker: SCHD
#     threshold: 0.10
tickers:
  - VOO
"""


def random_topic(word_count: int = 3) -> str:
    """Return a readable random topic like ``mango-eye-llama`` (distinct words)."""
    words = secrets.SystemRandom().sample(_TOPIC_WORDS, word_count)
    return "-".join(words)


def render_config(alert_topic: str, command_topic: str) -> str:
    """Fill the config template with the given topics."""
    return DEFAULT_CONFIG.replace(_ALERT, alert_topic).replace(_COMMAND, command_topic)
