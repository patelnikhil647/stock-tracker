import textwrap

import pytest

from stocktracker.config import load_config

VALID = textwrap.dedent(
    """
    threshold: 0.10
    ntfy:
      server: "https://ntfy.sh"
      topic: "mango-eye-llama"
      command_topic: "cocoa-fox-reed"
      priority: "high"
    state_db: "data/state.db"
    market_hours:
      enabled: false
      timezone: "America/New_York"
      open: "09:30"
      close: "16:00"
      weekdays: [0, 1, 2, 3, 4]
    """
)


def test_missing_config_raises_friendly_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="stocktracker init"):
        load_config(path=tmp_path / "config.yaml")


def test_loads_single_config(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(VALID)
    cfg = load_config(path=p)
    assert cfg.threshold == 0.10
    assert cfg.ntfy.topic == "mango-eye-llama"
    assert cfg.ntfy.command_topic == "cocoa-fox-reed"
    assert cfg.ntfy.server == "https://ntfy.sh"


def test_command_topic_defaults_empty_when_absent(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('ntfy:\n  topic: "a-b-c"\n')
    cfg = load_config(path=p)
    assert cfg.ntfy.command_topic == ""
