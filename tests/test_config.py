import os
import textwrap

import pytest

from stocktracker.config import load_config, load_dotenv

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


# --- load_dotenv -------------------------------------------------------------


def test_dotenv_missing_file_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv("_DOTENV_TEST_KEY", raising=False)
    load_dotenv(tmp_path / ".env")  # must not raise


def test_dotenv_loads_bare_key_value(tmp_path, monkeypatch):
    monkeypatch.delenv("_DOTENV_TEST_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("_DOTENV_TEST_KEY=hello\n")
    load_dotenv(p)
    assert os.environ.get("_DOTENV_TEST_KEY") == "hello"
    monkeypatch.delenv("_DOTENV_TEST_KEY")


def test_dotenv_strips_double_quotes(tmp_path, monkeypatch):
    monkeypatch.delenv("_DOTENV_TEST_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text('_DOTENV_TEST_KEY="quoted value"\n')
    load_dotenv(p)
    assert os.environ.get("_DOTENV_TEST_KEY") == "quoted value"
    monkeypatch.delenv("_DOTENV_TEST_KEY")


def test_dotenv_strips_single_quotes(tmp_path, monkeypatch):
    monkeypatch.delenv("_DOTENV_TEST_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("_DOTENV_TEST_KEY='sq'\n")
    load_dotenv(p)
    assert os.environ.get("_DOTENV_TEST_KEY") == "sq"
    monkeypatch.delenv("_DOTENV_TEST_KEY")


def test_dotenv_export_prefix(tmp_path, monkeypatch):
    monkeypatch.delenv("_DOTENV_TEST_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("export _DOTENV_TEST_KEY=exported\n")
    load_dotenv(p)
    assert os.environ.get("_DOTENV_TEST_KEY") == "exported"
    monkeypatch.delenv("_DOTENV_TEST_KEY")


def test_dotenv_does_not_override_existing_env(tmp_path, monkeypatch):
    monkeypatch.setenv("_DOTENV_TEST_KEY", "original")
    p = tmp_path / ".env"
    p.write_text("_DOTENV_TEST_KEY=overwrite\n")
    load_dotenv(p)
    assert os.environ.get("_DOTENV_TEST_KEY") == "original"


def test_dotenv_skips_comments_and_blanks(tmp_path, monkeypatch):
    monkeypatch.delenv("_DOTENV_TEST_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("# comment\n\n_DOTENV_TEST_KEY=real\n# another comment\n")
    load_dotenv(p)
    assert os.environ.get("_DOTENV_TEST_KEY") == "real"
    monkeypatch.delenv("_DOTENV_TEST_KEY")
