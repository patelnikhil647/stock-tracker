import io

import yaml

from stocktracker import templates
from stocktracker.cli import run_init
from stocktracker.config import load_config


def test_random_topic_format_and_word_length():
    for _ in range(50):
        topic = templates.random_topic()
        words = topic.split("-")
        assert len(words) == 3
        assert len(set(words)) == 3  # distinct
        assert all(w.isalpha() and 1 <= len(w) <= 6 for w in words)


def test_all_topic_words_are_short():
    assert all(len(w) <= 6 for w in templates._TOPIC_WORDS)


def test_run_init_creates_files(tmp_path):
    config_path = tmp_path / "config.yaml"
    watchlist_path = tmp_path / "watchlist.yaml"

    rc = run_init(config_path, watchlist_path, out=io.StringIO())
    assert rc == 0
    assert config_path.exists() and watchlist_path.exists()

    # Config loads and has distinct, filled-in topics (no placeholders left).
    cfg = load_config(path=config_path)
    assert cfg.ntfy.topic and "__" not in cfg.ntfy.topic
    assert cfg.ntfy.command_topic and "__" not in cfg.ntfy.command_topic
    assert cfg.ntfy.topic != cfg.ntfy.command_topic

    wl = yaml.safe_load(watchlist_path.read_text())
    assert wl["tickers"] == ["VOO"]


def test_run_init_refuses_overwrite_without_force(tmp_path):
    config_path = tmp_path / "config.yaml"
    watchlist_path = tmp_path / "watchlist.yaml"
    config_path.write_text("existing: true")

    rc = run_init(config_path, watchlist_path, out=io.StringIO())
    assert rc == 1
    assert config_path.read_text() == "existing: true"  # untouched


def test_run_init_force_overwrites(tmp_path):
    config_path = tmp_path / "config.yaml"
    watchlist_path = tmp_path / "watchlist.yaml"
    config_path.write_text("existing: true")

    rc = run_init(config_path, watchlist_path, force=True, out=io.StringIO())
    assert rc == 0
    assert "existing: true" not in config_path.read_text()
