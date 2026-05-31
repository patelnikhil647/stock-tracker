import textwrap

from stocktracker.config import PLACEHOLDER_TOPIC, _deep_merge, load_config

# A minimal valid example/template, mirroring config.example.yaml's shape.
EXAMPLE = textwrap.dedent(
    f"""
    threshold: 0.15
    ntfy:
      server: "https://ntfy.sh"
      topic: "{PLACEHOLDER_TOPIC}"
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


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_deep_merge_local_wins_and_siblings_survive():
    base = {"ntfy": {"server": "https://ntfy.sh", "topic": "x", "priority": "high"}}
    override = {"ntfy": {"topic": "my-secret"}}
    merged = _deep_merge(base, override)
    assert merged["ntfy"]["topic"] == "my-secret"      # override wins
    assert merged["ntfy"]["server"] == "https://ntfy.sh"  # sibling preserved
    assert merged["ntfy"]["priority"] == "high"


def test_partial_local_override_only_sets_topic(tmp_path):
    example = _write(tmp_path, "config.example.yaml", EXAMPLE)
    local = _write(tmp_path, "config.local.yaml", 'ntfy:\n  topic: "my-private-topic"\n')
    cfg = load_config(path=example, local_path=local)
    assert cfg.ntfy.topic == "my-private-topic"
    assert cfg.ntfy.server == "https://ntfy.sh"  # fell back to example
    assert cfg.ntfy.priority == "high"
    assert cfg.threshold == 0.15


def test_full_copy_local_loads(tmp_path):
    example = _write(tmp_path, "config.example.yaml", EXAMPLE)
    full = EXAMPLE.replace(PLACEHOLDER_TOPIC, "real-topic-123").replace(
        "threshold: 0.15", "threshold: 0.10"
    )
    local = _write(tmp_path, "config.local.yaml", full)
    cfg = load_config(path=example, local_path=local)
    assert cfg.ntfy.topic == "real-topic-123"
    assert cfg.threshold == 0.10


def test_placeholder_loads_without_raising(tmp_path):
    # load_config must NOT require a real topic, so read-only commands (list,
    # status) work before ntfy is configured. The placeholder is rejected later,
    # at send time (see test_notify). Here it should load with topic == placeholder.
    example = _write(tmp_path, "config.example.yaml", EXAMPLE)
    cfg = load_config(path=example, local_path=tmp_path / "config.local.yaml")
    assert cfg.ntfy.topic == PLACEHOLDER_TOPIC


def test_missing_topic_loads_empty(tmp_path):
    example = _write(tmp_path, "config.example.yaml", EXAMPLE)
    local = _write(tmp_path, "config.local.yaml", 'ntfy:\n  topic: ""\n')
    cfg = load_config(path=example, local_path=local)
    assert cfg.ntfy.topic == ""


def test_no_local_file_falls_back_to_example(tmp_path):
    # Example itself carries a real topic here -> should load with no local file.
    example_text = EXAMPLE.replace(PLACEHOLDER_TOPIC, "example-real-topic")
    example = _write(tmp_path, "config.example.yaml", example_text)
    cfg = load_config(path=example, local_path=tmp_path / "nope.yaml")
    assert cfg.ntfy.topic == "example-real-topic"
