import pytest

from stocktracker import notify
from stocktracker.config import NtfyConfig


def _ntfy(topic):
    return NtfyConfig(server="https://ntfy.sh", topic=topic, priority="high")


def test_send_rejects_empty_topic():
    with pytest.raises(notify.NotifyError, match="ntfy.topic is not set"):
        notify.send(_ntfy(""), title="t", message="m")


def test_send_rejects_non_latin1_title():
    # Emoji can't go in an HTTP header; should raise a clean NotifyError rather
    # than an opaque UnicodeEncodeError from deep in the HTTP stack.
    with pytest.raises(notify.NotifyError, match="non-Latin-1"):
        notify.send(_ntfy("my-topic"), title="✅ hi", message="m")


def test_send_posts_with_valid_topic(monkeypatch):
    calls = {}

    class FakeResp:
        def raise_for_status(self):
            pass

    def fake_post(url, data=None, headers=None, timeout=None):
        calls["url"] = url
        calls["headers"] = headers
        calls["data"] = data
        return FakeResp()

    monkeypatch.setattr(notify.requests, "post", fake_post)
    notify.send(_ntfy("my-real-topic"), title="Hello", message="body", tags="tada")

    assert calls["url"] == "https://ntfy.sh/my-real-topic"
    assert calls["headers"]["Title"] == "Hello"
    assert calls["headers"]["Tags"] == "tada"
    assert calls["data"] == b"body"
